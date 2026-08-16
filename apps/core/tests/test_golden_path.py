"""The golden path: one demo, start to finish, through the real screens.

This is the test that proves the product is a product and not eleven apps that
each pass their own suite. It walks the exact story the five-minute demo tells,
in order, through the HTTP client — every POST is a form somebody fills, every
GET a page somebody opens:

    invitar a un técnico → dar de alta un equipo → escribir un checklist →
    programar un plan → correr el programador → ejecutar la OT desde el
    celular → verificarla → sacar el informe → reportar una falla →
    convertirla en OT → leer el tablero → leer la auditoría

Each step asserts the least that proves it happened, and `step()` stamps the
step's name onto any failure — so when a future brief breaks a link in the
chain, the report names the link instead of pointing at line 300 of a long
test.

It creates only what the story needs and leaves nothing behind: uploads go to a
temporary MEDIA_ROOT that is deleted afterwards, mail goes to `locmem`, and the
database work is rolled back by `TestCase` like every other test here. Nothing
in it depends on the demo seeds or on another test having run first.
"""

import io
import re
import tempfile
from contextlib import contextmanager

from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import Site, User
from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    StaffUserFactory,
    SupervisorUserFactory,
)
from apps.assets.models import Asset, AssetCategory
from apps.audit.models import AuditLog
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem
from apps.kpis import periods, queries
from apps.maintenance.models import MaintenancePlan, MeterReading
from apps.reports import documents, pdf
from apps.reports.models import NotificationLog
from apps.requests_.models import MaintenanceRequest
from apps.workorders.models import WorkOrder, WorkOrderChecklistItem, WorkOrderPhoto

TEMP_PASSWORD_IN_EMAIL = re.compile(r"Contraseña temporal:\s*(\S+)")


def a_real_jpeg() -> io.BytesIO:
    """Actual JPEG bytes: the upload pipeline checks magic bytes and re-encodes
    with Pillow, so a file of `b"not-an-image"` would be rejected — correctly."""
    buffer = io.BytesIO()
    Image.new("RGB", (160, 120), color="steelblue").save(buffer, format="JPEG")
    buffer.seek(0)
    buffer.name = "evidencia.jpg"
    return buffer


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class GoldenPathTests(TestCase):
    """One test. It is long because the story is long."""

    def setUp(self):
        # Uploads live outside the database, so a rollback would not clean them
        # up: they get their own directory, and it goes away with the test.
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.media.name)
        media_override.enable()
        self.addCleanup(media_override.disable)

        self.company = CompanyFactory(name="Empaques de Prueba S.A.S.")
        self.company.subscription.max_users = 10
        self.company.subscription.save(update_fields=["max_users"])

        self.admin = AdminUserFactory(company=self.company, username="ana.admin")
        self.supervisor = SupervisorUserFactory(
            company=self.company, username="sara.super", first_name="Sara", last_name="Peña"
        )
        self.office = StaffUserFactory(company=self.company, username="olga.oficina")

        self.today = timezone.localdate()

    # --- Narration ----------------------------------------------------------

    @contextmanager
    def step(self, name: str):
        """Label every failure inside the block with the step it broke.

        The point of a smoke test this long is diagnosis: "[6. el técnico
        ejecuta la OT] ..." tells whoever reads the CI output which part of the
        product stopped working, without them opening the file.
        """
        try:
            yield
        except AssertionError as failure:
            raise AssertionError(f"[{name}] {failure}") from failure
        except Exception as failure:  # a 500, a missing URL, a broken form
            raise AssertionError(
                f"[{name}] reventó con {type(failure).__name__}: {failure}"
            ) from failure

    def client_for(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def post(self, client, url: str, data: dict, *, expect=302, **extra):
        response = client.post(url, data, **extra)
        assert response.status_code == expect, (
            f"POST {url} respondió {response.status_code}, no {expect}. "
            f"{self._form_errors(response)}"
        )
        return response

    @staticmethod
    def _form_errors(response) -> str:
        """Django re-renders a form with 200 on validation errors, so a failed
        POST looks like a success unless somebody reads the errors out."""
        form = response.context.get("form") if response.context else None
        return f"Errores del formulario: {form.errors.as_json()}" if form else ""

    def audit_rows(self, model_label: str, action: str | None = None):
        rows = AuditLog.objects.unscoped().filter(
            company=self.company, model_label=model_label
        )
        return rows.filter(action=action) if action else rows

    # --- The story ----------------------------------------------------------

    def test_the_whole_demo_runs_end_to_end(self):
        admin = self.client_for(self.admin)

        # 1 ------------------------------------------------------------------
        with self.step("1. el admin invita a un técnico"):
            self.post(
                admin,
                reverse("user_invite"),
                {
                    "username": "tomas.tecnico",
                    "email": "tomas.tecnico@example.com",
                    "first_name": "Tomás",
                    "last_name": "Ariza",
                    "role": User.Role.TECHNICIAN,
                    "whatsapp_phone": "",
                },
            )
            technician = User.objects.get(username="tomas.tecnico")
            assert technician.company_id == self.company.pk
            assert technician.role == User.Role.TECHNICIAN
            assert len(mail.outbox) == 1, "la invitación es el correo: sin correo no hay cuenta"
            assert NotificationLog.objects.unscoped().filter(
                company=self.company, kind=NotificationLog.Kind.TEMP_PASSWORD
            ).exists()

            # The temporary password exists only inside that email. Logging in
            # with it is what proves the invitation is usable, not just sent.
            match = TEMP_PASSWORD_IN_EMAIL.search(mail.outbox[0].body)
            assert match, "el correo de invitación no trae la contraseña temporal"
            technician_client = Client()
            assert technician_client.login(
                username="tomas.tecnico", password=match.group(1)
            ), "la contraseña temporal del correo no sirve para entrar"

        # 2 ------------------------------------------------------------------
        with self.step("2. el admin da de alta un equipo"):
            self.post(admin, reverse("site_create"), {"name": "Planta Norte", "address": "Km 2"})
            self.post(admin, reverse("assetcategory_create"), {"name": "Empacadora"})
            # `.unscoped()` throughout: a test runs outside the request cycle,
            # where the scoped managers answer nothing at all
            # (apps/core/tenancy.py). The views under test do have the
            # contextvar, which is the point.
            site = Site.objects.unscoped().get(company=self.company, name="Planta Norte")
            category = AssetCategory.objects.unscoped().get(
                company=self.company, name="Empacadora"
            )

            self.post(
                admin,
                reverse("asset_create"),
                {
                    "site": site.pk,
                    "category": category.pk,
                    "code": "FLW-99",
                    "name": "Empacadora de la demo",
                    "brand": "Sabana Pack",
                    "model": "SP-450",
                    "serial_number": "SP450-DEMO-1",
                    "criticality": Asset.Criticality.ALTA,
                    "location_detail": "Línea 1",
                    "spec_key": ["Voltaje", "Presión de aire"],
                    "spec_value": ["220 V trifásico", "6 bar"],
                },
            )
            asset = Asset.objects.unscoped().get(company=self.company, code="FLW-99")
            assert asset.specs[0]["key"] == "Voltaje"
            assert self.audit_rows("assets.Asset", AuditLog.Action.CREATE).exists()

        # 3 ------------------------------------------------------------------
        with self.step("3. el admin escribe un checklist"):
            self.post(
                admin,
                reverse("checklisttemplate_create"),
                {"name": "Inspección de la demo", "category": category.pk},
            )
            template = ChecklistTemplate.objects.unscoped().get(
                company=self.company, name="Inspección de la demo"
            )
            items_url = reverse("checklistitem_create", args=[template.pk])
            self.post(
                admin,
                items_url,
                {
                    "text": "Limpieza general de la máquina",
                    "item_type": ChecklistTemplateItem.ItemType.CHECK,
                    "unit": "",
                    "min_value": "",
                    "max_value": "",
                    "required": "on",
                },
            )
            self.post(
                admin,
                items_url,
                {
                    "text": "Presión de aire en la línea",
                    "item_type": ChecklistTemplateItem.ItemType.NUMERIC,
                    "unit": "bar",
                    "min_value": "5",
                    "max_value": "7",
                    "required": "on",
                },
            )
            assert (
                ChecklistTemplateItem.objects.unscoped().filter(template=template).count() == 2
            )

        # 4 ------------------------------------------------------------------
        with self.step("4. el admin programa un plan preventivo"):
            self.post(
                admin,
                reverse("maintenanceplan_create", args=[asset.pk]),
                {
                    "name": "Preventivo semanal de la demo",
                    "kind": MaintenancePlan.Kind.PREVENTIVO,
                    "frequency_type": MaintenancePlan.FrequencyType.CALENDAR,
                    "interval_preset": "7",
                    "interval_days": "",
                    "next_due_date": self.today.isoformat(),
                    "meter_interval_hours": "",
                    "checklist_template": template.pk,
                    "default_assignee": technician.pk,
                    "estimated_minutes": "45",
                    "is_active": "on",
                },
            )
            plan = MaintenancePlan.objects.unscoped().get(
                company=self.company, name="Preventivo semanal de la demo"
            )
            assert plan.interval_days == 7
            assert plan.next_due_date == self.today

        # 5 ------------------------------------------------------------------
        with self.step("5. el programador crea la OT sola"):
            call_command("generate_work_orders", verbosity=0)

            work_order = WorkOrder.objects.unscoped().get(plan=plan, due_date=self.today)
            assert work_order.status == WorkOrder.Status.ABIERTA
            # The checklist was frozen onto the work order at birth: it is a
            # copy, not a pointer (CLAUDE.md rule 4).
            assert (
                WorkOrderChecklistItem.objects.unscoped()
                .filter(work_order=work_order)
                .count()
                == 2
            )

            # And it is idempotent: a second run creates nothing.
            call_command("generate_work_orders", verbosity=0)
            assert (
                WorkOrder.objects.unscoped().filter(plan=plan, due_date=self.today).count() == 1
            )

        supervisor = self.client_for(self.supervisor)

        # 6 ------------------------------------------------------------------
        with self.step("6. el supervisor la asigna y el técnico la ejecuta desde el celular"):
            self.post(
                supervisor,
                reverse("workorder_assign", args=[work_order.pk]),
                {"assignee": technician.pk},
            )
            self.post(technician_client, reverse("workorder_start", args=[work_order.pk]), {})
            work_order.refresh_from_db()
            assert work_order.status == WorkOrder.Status.EN_PROGRESO

            execute_url = reverse("workorder_execute", args=[work_order.pk])
            screen = technician_client.get(execute_url)
            assert screen.status_code == 200
            assert "Presión de aire en la línea" in screen.content.decode()

            items = list(
                WorkOrderChecklistItem.objects.unscoped()
                .filter(work_order=work_order)
                .order_by("order")
            )
            check_item, numeric_item = items
            self.post(
                technician_client,
                reverse("workorder_item_save", args=[work_order.pk, check_item.pk]),
                {"result": WorkOrderChecklistItem.Result.OK, "note": ""},
                expect=200,
                HTTP_HX_REQUEST="true",
            )
            # 8,4 bar on a 5–7 bar item. The technician records the reading; the
            # product decides it is a failure, because that is arithmetic.
            self.post(
                technician_client,
                reverse("workorder_item_save", args=[work_order.pk, numeric_item.pk]),
                {"result": "", "numeric_value": "8,4", "note": "Regulador descalibrado."},
                expect=200,
                HTTP_HX_REQUEST="true",
            )
            numeric_item.refresh_from_db()
            assert numeric_item.result == WorkOrderChecklistItem.Result.FALLA, (
                "una medida fuera de rango tiene que quedar como falla sola"
            )

            self.post(
                technician_client,
                reverse("workorder_photo_upload", args=[work_order.pk]),
                {"image": a_real_jpeg(), "caption": "Manómetro de la línea"},
            )
            assert (
                WorkOrderPhoto.objects.unscoped().filter(work_order=work_order).count() == 1
            )

            # The hour meter, from the equipment record — which is also what
            # makes the closing form ask for it.
            self.post(
                technician_client,
                reverse("meterreading_create", args=[asset.pk]),
                {"reading_hours": "1250.5"},
            )
            assert MeterReading.objects.unscoped().filter(asset=asset).count() == 1

            self.post(
                technician_client,
                reverse("workorder_complete", args=[work_order.pk]),
                {
                    "work_done": "Rutina ejecutada. Se reporta el regulador fuera de rango.",
                    "downtime_minutes": "35",
                    "labor_cost_cop": "90000",
                    "parts_cost_cop": "45000",
                    "meter_reading_hours": "1252.0",
                },
            )
            work_order.refresh_from_db()
            assert work_order.status == WorkOrder.Status.TERMINADA
            assert work_order.completed_by_id == technician.pk
            assert work_order.downtime_minutes == 35
            assert MeterReading.objects.unscoped().filter(asset=asset).count() == 2

        # 7 ------------------------------------------------------------------
        with self.step("7. el supervisor verifica y la OT queda sellada"):
            self.post(supervisor, reverse("workorder_verify", args=[work_order.pk]), {})
            work_order.refresh_from_db()
            assert work_order.status == WorkOrder.Status.VERIFICADA
            assert work_order.verified_by_id == self.supervisor.pk
            assert work_order.verified_by_id != work_order.completed_by_id, (
                "quien ejecuta no verifica (CLAUDE.md regla 3)"
            )

        # 8 ------------------------------------------------------------------
        with self.step("8. el informe de la OT sale en PDF"):
            document = documents.build_work_order_report(work_order)
            assert "Sara Peña" in document.html
            assert "Regulador descalibrado." in document.html

            response = self.client_for(self.supervisor).get(
                reverse("workorder_report_pdf", args=[work_order.pk])
            )
            if pdf.engine_available():
                assert response.status_code == 200
                assert response["Content-Type"] == "application/pdf"
                assert response.content.startswith(b"%PDF-")
            else:
                # No GTK on this machine (see README). The product's promise is
                # then a Spanish message and a redirect, never a 500 in front
                # of a customer — CI renders the real bytes.
                assert response.status_code == 302

        # 9 ------------------------------------------------------------------
        with self.step("9. la oficina reporta una falla"):
            office = self.client_for(self.office)
            self.post(
                office,
                reverse("maintenancerequest_create", args=[asset.pk]),
                {"description": "La máquina hace un ruido raro al arrancar."},
            )
            failure_report = MaintenanceRequest.objects.unscoped().get(
                company=self.company, asset=asset
            )
            assert failure_report.status == MaintenanceRequest.Status.NUEVA
            assert failure_report.reported_by_id == self.office.pk

        # 10 -----------------------------------------------------------------
        with self.step("10. el supervisor la convierte en OT correctiva"):
            self.post(
                supervisor,
                reverse("maintenancerequest_convert", args=[failure_report.pk]),
                {"priority": WorkOrder.Priority.ALTA},
            )
            corrective = WorkOrder.objects.unscoped().get(source_request=failure_report)
            failure_report.refresh_from_db()
            assert failure_report.status == MaintenanceRequest.Status.CONVERTIDA
            assert corrective.type == WorkOrder.Type.CORRECTIVO
            assert corrective.failure_description == failure_report.description

            # A double tap on a phone is not a second work order.
            self.post(
                supervisor,
                reverse("maintenancerequest_convert", args=[failure_report.pk]),
                {"priority": WorkOrder.Priority.ALTA},
            )
            assert (
                WorkOrder.objects.unscoped().filter(source_request=failure_report).count() == 1
            )

        # 11 -----------------------------------------------------------------
        with self.step("11. el tablero refleja lo que acaba de pasar"):
            compliance = queries.pm_compliance(self.company.pk, periods.resolve(None))
            assert compliance.scheduled == 1
            assert compliance.on_time == 1, "la OT se cerró el mismo día en que estaba programada"

            dashboard = supervisor.get(reverse("kpi_dashboard"))
            assert dashboard.status_code == 200
            page = dashboard.content.decode()
            assert "1 de 1 a tiempo" in page
            assert "35 min de parada registrados" in page, (
                "la parada que registró el técnico tiene que llegar al tablero"
            )

        # 12 -----------------------------------------------------------------
        with self.step("12. la auditoría cuenta la historia completa"):
            assert self.audit_rows("accounts.User", AuditLog.Action.CREATE).exists()
            assert self.audit_rows("maintenance.MaintenancePlan", AuditLog.Action.CREATE).exists()
            assert self.audit_rows("requests.MaintenanceRequest", AuditLog.Action.CREATE).exists()

            transitions = list(
                self.audit_rows("workorders.WorkOrder", AuditLog.Action.TRANSITION)
                .order_by("id")
                .values_list("changes", flat=True)
            )
            states = [row["status"]["a"] for row in transitions if "status" in row]
            assert states == [
                WorkOrder.Status.ASIGNADA,
                WorkOrder.Status.EN_PROGRESO,
                WorkOrder.Status.TERMINADA,
                WorkOrder.Status.VERIFICADA,
            ], states

            screen = admin.get(reverse("auditlog_list"))
            assert screen.status_code == 200
            assert self.admin.get_username() in screen.content.decode()
