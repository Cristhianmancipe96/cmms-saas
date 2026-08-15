"""The screens: what renders, who may open them, what a POST actually writes."""

import io
from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.checklists.tests.factories import (
    ChecklistTemplateFactory,
    create_flowpac_inspeccion_semanal,
)
from apps.maintenance.models import MeterReading
from apps.maintenance.tests.factories import MeterPlanFactory
from apps.workorders import services
from apps.workorders.models import WorkOrder, WorkOrderChecklistItem, WorkOrderPhoto
from apps.workorders.tests.factories import WorkOrderChecklistItemFactory, WorkOrderFactory


def real_jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), color="orange").save(buffer, format="JPEG")
    return buffer.getvalue()


class MyWorkOrdersTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.client.force_login(self.technician)
        self.today = timezone.localdate()
        self.url = reverse("workorder_mine")

    def test_the_empty_state_says_where_work_comes_from(self):
        content = self.client.get(self.url).content.decode()

        assert "No tienes órdenes de trabajo asignadas." in content

    def test_overdue_today_and_upcoming_are_separate_groups(self):
        WorkOrderFactory(
            asset=self.asset,
            assigned_to=self.technician,
            status=WorkOrder.Status.ASIGNADA,
            due_date=self.today - timedelta(days=2),
        )
        WorkOrderFactory(
            asset=self.asset,
            assigned_to=self.technician,
            status=WorkOrder.Status.ASIGNADA,
            due_date=self.today,
        )
        WorkOrderFactory(
            asset=self.asset,
            assigned_to=self.technician,
            status=WorkOrder.Status.ASIGNADA,
            due_date=self.today + timedelta(days=10),
        )

        response = self.client.get(self.url)

        assert len(response.context["overdue"]) == 1
        assert len(response.context["due_today"]) == 1
        assert len(response.context["upcoming"]) == 1
        assert "vt-row--vencido" in response.content.decode()

    def test_another_technicians_work_is_not_listed(self):
        other = TechnicianUserFactory(company=self.company)
        WorkOrderFactory(
            asset=self.asset, assigned_to=other, status=WorkOrder.Status.ASIGNADA
        )

        assert self.client.get(self.url).context["total"] == 0

    def test_finished_work_is_off_the_list(self):
        WorkOrderFactory(
            asset=self.asset,
            assigned_to=self.technician,
            status=WorkOrder.Status.TERMINADA,
        )

        assert self.client.get(self.url).context["total"] == 0


class WorkOrderListTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)
        self.url = reverse("workorder_list")
        self.today = timezone.localdate()

    def test_the_empty_state_explains_where_work_orders_come_from(self):
        content = self.client.get(self.url).content.decode()

        assert "Aún no hay órdenes de trabajo." in content

    def test_an_overdue_work_order_is_tinted_and_counted(self):
        WorkOrderFactory(
            asset=self.asset,
            status=WorkOrder.Status.ASIGNADA,
            due_date=self.today - timedelta(days=3),
        )

        response = self.client.get(self.url)

        assert response.context["overdue_count"] == 1
        assert "vt-row--vencido" in response.content.decode()

    def test_the_status_filter_narrows_the_list(self):
        WorkOrderFactory(asset=self.asset, status=WorkOrder.Status.ABIERTA)
        WorkOrderFactory(asset=self.asset, status=WorkOrder.Status.TERMINADA)

        response = self.client.get(self.url, {"estado": "terminada"})

        assert len(response.context["work_orders"]) == 1
        assert response.context["work_orders"][0].status == WorkOrder.Status.TERMINADA

    def test_the_technician_filter_narrows_the_list(self):
        mine = TechnicianUserFactory(company=self.company)
        WorkOrderFactory(asset=self.asset, assigned_to=mine)
        WorkOrderFactory(asset=self.asset, assigned_to=None)

        response = self.client.get(self.url, {"tecnico": mine.pk})

        assert len(response.context["work_orders"]) == 1

    def test_the_overdue_filter_excludes_finished_work(self):
        WorkOrderFactory(
            asset=self.asset,
            status=WorkOrder.Status.TERMINADA,
            due_date=self.today - timedelta(days=5),
        )
        WorkOrderFactory(
            asset=self.asset,
            status=WorkOrder.Status.ABIERTA,
            due_date=self.today - timedelta(days=5),
        )

        response = self.client.get(self.url, {"vencidas": "1"})

        assert len(response.context["work_orders"]) == 1

    def test_office_staff_can_read_the_list(self):
        self.client.force_login(StaffUserFactory(company=self.company))

        assert self.client.get(self.url).status_code == 200


class WorkOrderDetailTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.client.force_login(self.supervisor)

    def test_an_open_work_order_offers_the_assign_form_to_a_supervisor(self):
        work_order = WorkOrderFactory(asset=self.asset)

        response = self.client.get(reverse("workorder_detail", args=[work_order.pk]))

        assert response.context["assign_form"] is not None
        assert self.technician in response.context["assign_form"].fields["assignee"].queryset

    def test_office_staff_are_not_offered_as_assignees(self):
        StaffUserFactory(company=self.company)
        work_order = WorkOrderFactory(asset=self.asset)

        response = self.client.get(reverse("workorder_detail", args=[work_order.pk]))

        queryset = response.context["assign_form"].fields["assignee"].queryset
        assert not queryset.filter(role="staff").exists()

    def test_a_technician_sees_no_assign_form(self):
        work_order = WorkOrderFactory(asset=self.asset)
        self.client.force_login(self.technician)

        response = self.client.get(reverse("workorder_detail", args=[work_order.pk]))

        assert response.context["assign_form"] is None

    def test_a_verified_work_order_shows_the_seal_and_no_actions(self):
        executor = TechnicianUserFactory(company=self.company)
        work_order = WorkOrderFactory(asset=self.asset, assigned_to=executor)
        WorkOrder.objects.unscoped().filter(pk=work_order.pk).update(
            status=WorkOrder.Status.VERIFICADA,
            completed_by=executor,
            verified_by=self.supervisor,
            verified_at=timezone.now(),
        )

        response = self.client.get(reverse("workorder_detail", args=[work_order.pk]))
        content = response.content.decode()

        assert response.context["actions"] == []
        assert "vt-seal" in content
        assert "Ya no se puede modificar." in content

    def test_assigning_through_the_view_moves_the_work_order(self):
        work_order = WorkOrderFactory(asset=self.asset)

        response = self.client.post(
            reverse("workorder_assign", args=[work_order.pk]),
            {"assignee": self.technician.pk},
        )

        work_order.refresh_from_db()
        assert response.status_code == 302
        assert work_order.status == WorkOrder.Status.ASIGNADA
        assert work_order.assigned_to_id == self.technician.pk

    def test_a_technician_cannot_assign(self):
        work_order = WorkOrderFactory(asset=self.asset)
        self.client.force_login(self.technician)

        response = self.client.post(
            reverse("workorder_assign", args=[work_order.pk]),
            {"assignee": self.technician.pk},
            follow=True,
        )

        work_order.refresh_from_db()
        assert work_order.status == WorkOrder.Status.ABIERTA
        assert "Solo un supervisor o un administrador puede asignar" in response.content.decode()

    def test_the_timeline_lists_the_recorded_events(self):
        work_order = WorkOrderFactory(asset=self.asset, assigned_to=self.technician)
        WorkOrder.objects.unscoped().filter(pk=work_order.pk).update(
            status=WorkOrder.Status.TERMINADA,
            started_at=timezone.now(),
            finished_at=timezone.now(),
            completed_by=self.technician,
        )

        response = self.client.get(reverse("workorder_detail", args=[work_order.pk]))
        labels = [event["label"] for event in response.context["timeline"]]

        assert labels == ["Creada", "Iniciada", "Terminada"]


class ExecutionScreenAccessTests(TestCase):
    """Acceptance criterion 7, second half: technician A cannot open
    technician B's execution screen, same company or not."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.assignee = TechnicianUserFactory(company=self.company)
        self.work_order = WorkOrderFactory(
            asset=self.asset,
            status=WorkOrder.Status.EN_PROGRESO,
            assigned_to=self.assignee,
        )
        self.url = reverse("workorder_execute", args=[self.work_order.pk])

    def test_the_assignee_can_open_it(self):
        self.client.force_login(self.assignee)

        assert self.client.get(self.url).status_code == 200

    def test_another_technician_of_the_same_company_gets_403(self):
        self.client.force_login(TechnicianUserFactory(company=self.company))

        assert self.client.get(self.url).status_code == 403

    def test_office_staff_get_403(self):
        self.client.force_login(StaffUserFactory(company=self.company))

        assert self.client.get(self.url).status_code == 403

    def test_another_technician_cannot_read_a_row_through_a_failed_post(self):
        """The service would refuse the write, but the response renders the
        checklist row — so the POST endpoints carry the same gate as the GET."""
        item = WorkOrderChecklistItemFactory(work_order=self.work_order, order=1)
        self.client.force_login(TechnicianUserFactory(company=self.company))

        response = self.client.post(
            reverse("workorder_item_save", args=[self.work_order.pk, item.pk]),
            {"result": "ok"},
        )

        assert response.status_code == 403

    def test_another_technician_cannot_post_the_closing_form(self):
        self.client.force_login(TechnicianUserFactory(company=self.company))

        response = self.client.post(
            reverse("workorder_complete", args=[self.work_order.pk]), {"work_done": "x"}
        )

        assert response.status_code == 403
        self.work_order.refresh_from_db()
        assert self.work_order.status == WorkOrder.Status.EN_PROGRESO

    def test_a_supervisor_may_look_but_not_answer(self):
        self.client.force_login(SupervisorUserFactory(company=self.company))

        response = self.client.get(self.url)

        content = response.content.decode()

        assert response.status_code == 200
        assert response.context["can_answer"] is False
        # Substrings, not the whole sentence: the template wraps it across
        # source lines, and asserting the joined-up text makes the test fail on
        # a reflow that changed nothing a user can see.
        assert "Estás viendo la ejecución de" in content
        assert str(self.assignee) in content
        # No «Terminar OT» either: the closing form is the assignee's.
        assert "Terminar OT" not in content


class ChecklistExecutionTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.template = create_flowpac_inspeccion_semanal(company=self.company)
        self.work_order = WorkOrderFactory(
            asset=self.asset,
            status=WorkOrder.Status.EN_PROGRESO,
            assigned_to=self.technician,
        )
        services.snapshot_checklist(self.work_order, self.template)
        self.items = list(services.checklist_items(self.work_order))
        self.client.force_login(self.technician)
        self.execute_url = reverse("workorder_execute", args=[self.work_order.pk])

    def _item_url(self, item):
        return reverse("workorder_item_save", args=[self.work_order.pk, item.pk])

    def test_the_screen_renders_every_snapshotted_item(self):
        content = self.client.get(self.execute_url).content.decode()

        assert "Verificar nivel de aceite" in content
        assert "Presión de aire de la línea" in content
        assert "Rango esperado: 5.00 – 7.00 bar" in content

    def test_saving_one_item_via_htmx_returns_the_row_and_the_progress(self):
        response = self.client.post(
            self._item_url(self.items[0]),
            {"result": "ok", "note": ""},
            headers={"hx-request": "true"},
        )
        content = response.content.decode()

        assert response.status_code == 200
        assert f'id="item-{self.items[0].pk}"' in content
        assert 'id="checklist-progress"' in content
        assert 'hx-swap-oob="true"' in content
        assert "1 de 3 respondidos" in content

    def test_an_out_of_range_measurement_comes_back_marked_as_a_failure(self):
        numeric = self.items[1]

        response = self.client.post(
            self._item_url(numeric),
            {"result": "", "numeric_value": "9.5"},
            headers={"hx-request": "true"},
        )
        content = response.content.decode()

        assert "is-falla" in content
        assert "queda registrado como falla" in content
        numeric.refresh_from_db()
        assert numeric.result == WorkOrderChecklistItem.Result.FALLA

    def test_a_comma_decimal_is_accepted(self):
        """es-CO keyboards put a comma there; rejecting it teaches nothing."""
        numeric = self.items[1]

        self.client.post(self._item_url(numeric), {"result": "", "numeric_value": "6,5"})

        numeric.refresh_from_db()
        assert numeric.numeric_value == Decimal("6.50")
        assert numeric.result == WorkOrderChecklistItem.Result.OK

    def test_without_htmx_the_same_post_redirects_back_to_the_screen(self):
        response = self.client.post(self._item_url(self.items[0]), {"result": "ok"})

        assert response.status_code == 302
        assert response.url == self.execute_url
        self.items[0].refresh_from_db()
        assert self.items[0].result == "ok"

    def test_a_refusal_is_rendered_inside_the_row_in_spanish(self):
        response = self.client.post(
            self._item_url(self.items[1]),
            {"result": "", "numeric_value": ""},
            headers={"hx-request": "true"},
        )

        assert "Escribe el valor medido." in response.content.decode()

    def test_completing_with_required_items_pending_is_refused_in_spanish(self):
        response = self.client.post(
            reverse("workorder_complete", args=[self.work_order.pk]),
            {"work_done": "Listo"},
            follow=True,
        )

        assert "obligatorio" in response.content.decode()
        self.work_order.refresh_from_db()
        assert self.work_order.status == WorkOrder.Status.EN_PROGRESO

    def test_completing_with_everything_answered_moves_to_terminada(self):
        self.client.post(self._item_url(self.items[0]), {"result": "ok"})
        self.client.post(self._item_url(self.items[1]), {"result": "", "numeric_value": "6"})
        self.client.post(self._item_url(self.items[2]), {"note": "Sin novedades"})

        response = self.client.post(
            reverse("workorder_complete", args=[self.work_order.pk]),
            {
                "work_done": "Inspección completa",
                "downtime_minutes": "30",
                "labor_cost_cop": "50000",
                "parts_cost_cop": "0",
            },
        )

        self.work_order.refresh_from_db()
        assert response.status_code == 302
        assert self.work_order.status == WorkOrder.Status.TERMINADA
        assert self.work_order.completed_by_id == self.technician.pk
        assert self.work_order.downtime_minutes == 30

    def test_a_negative_cost_is_rejected_by_the_form(self):
        response = self.client.post(
            reverse("workorder_complete", args=[self.work_order.pk]),
            {"labor_cost_cop": "-5000"},
        )

        self.work_order.refresh_from_db()
        assert response.status_code == 200
        assert self.work_order.status == WorkOrder.Status.EN_PROGRESO

    def test_the_meter_field_only_appears_on_a_metered_machine(self):
        assert "Horómetro al cierre" not in self.client.get(self.execute_url).content.decode()

        MeterPlanFactory(company=self.company, asset=self.asset)

        assert "Horómetro al cierre" in self.client.get(self.execute_url).content.decode()

    def test_closing_a_metered_machine_records_the_reading(self):
        MeterPlanFactory(company=self.company, asset=self.asset)
        for item in self.items:
            services.record_item_result(
                self.work_order,
                item,
                user=self.technician,
                result="ok" if item.item_type != "text" else "",
                numeric_value=Decimal("6") if item.item_type == "numeric" else None,
                note="ok" if item.item_type == "text" else "",
            )

        self.client.post(
            reverse("workorder_complete", args=[self.work_order.pk]),
            {"work_done": "Listo", "meter_reading_hours": "1300.25"},
        )

        reading = MeterReading.objects.unscoped().get(asset=self.asset)
        assert reading.reading_hours == Decimal("1300.25")
        assert reading.source == MeterReading.Source.WORK_ORDER

    def test_a_backwards_reading_at_closing_is_a_message_not_a_500(self):
        from apps.maintenance.tests.factories import MeterReadingFactory

        MeterPlanFactory(company=self.company, asset=self.asset)
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("5000.00"))
        for item in self.items:
            services.record_item_result(
                self.work_order,
                item,
                user=self.technician,
                result="ok" if item.item_type != "text" else "",
                numeric_value=Decimal("6") if item.item_type == "numeric" else None,
                note="ok" if item.item_type == "text" else "",
            )

        response = self.client.post(
            reverse("workorder_complete", args=[self.work_order.pk]),
            {"work_done": "Listo", "meter_reading_hours": "100"},
            follow=True,
        )

        assert response.status_code == 200
        assert "no puede ser menor" in response.content.decode()
        self.work_order.refresh_from_db()
        assert self.work_order.status == WorkOrder.Status.EN_PROGRESO


class PhotoEvidenceTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.work_order = WorkOrderFactory(
            asset=self.asset,
            status=WorkOrder.Status.EN_PROGRESO,
            assigned_to=self.technician,
        )
        self.client.force_login(self.technician)
        self.url = reverse("workorder_photo_upload", args=[self.work_order.pk])

    def test_a_real_photo_is_stored_and_reencoded(self):
        upload = SimpleUploadedFile("foto.jpg", real_jpeg_bytes(), content_type="image/jpeg")

        response = self.client.post(self.url, {"image": upload, "caption": "Rodamiento"})

        photo = WorkOrderPhoto.objects.unscoped().get(work_order=self.work_order)
        assert response.status_code == 302
        assert photo.caption == "Rodamiento"
        assert photo.taken_by_id == self.technician.pk
        assert photo.company_id == self.company.pk
        # The stored name is server-generated, never the phone's.
        assert "foto.jpg" not in photo.image.name
        assert photo.image.name.startswith("workorders/photos/")

    def test_a_forbidden_extension_is_rejected_in_spanish(self):
        upload = SimpleUploadedFile(
            "shell.exe", b"MZ-not-an-image", content_type="application/octet-stream"
        )

        response = self.client.post(self.url, {"image": upload}, follow=True)

        assert WorkOrderPhoto.objects.unscoped().count() == 0
        assert "Formato no permitido" in response.content.decode()

    def test_bytes_that_are_not_an_image_are_rejected(self):
        upload = SimpleUploadedFile("falsa.jpg", b"not an image at all", content_type="image/jpeg")

        response = self.client.post(self.url, {"image": upload}, follow=True)

        assert WorkOrderPhoto.objects.unscoped().count() == 0
        assert "no es una imagen válida" in response.content.decode()

    def test_another_technician_cannot_attach_a_photo(self):
        self.client.force_login(TechnicianUserFactory(company=self.company))
        upload = SimpleUploadedFile("foto.jpg", real_jpeg_bytes(), content_type="image/jpeg")

        response = self.client.post(self.url, {"image": upload})

        assert response.status_code == 403
        assert WorkOrderPhoto.objects.unscoped().count() == 0

    def test_photos_are_served_through_the_gated_view_not_a_media_url(self):
        upload = SimpleUploadedFile("foto.jpg", real_jpeg_bytes(), content_type="image/jpeg")
        self.client.post(self.url, {"image": upload})
        photo = WorkOrderPhoto.objects.unscoped().get(work_order=self.work_order)

        response = self.client.get(
            reverse("workorder_photo_download", args=[self.work_order.pk, photo.pk])
        )

        assert response.status_code == 200
        assert response["Content-Type"] == "image/jpeg"

    def test_an_anonymous_visitor_is_sent_to_the_login_page(self):
        upload = SimpleUploadedFile("foto.jpg", real_jpeg_bytes(), content_type="image/jpeg")
        self.client.post(self.url, {"image": upload})
        photo = WorkOrderPhoto.objects.unscoped().get(work_order=self.work_order)
        self.client.logout()

        response = self.client.get(
            reverse("workorder_photo_download", args=[self.work_order.pk, photo.pk])
        )

        assert response.status_code == 302
        assert reverse("login") in response.url


class VerifyAndCancelScreenTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.work_order = WorkOrderFactory(asset=self.asset, assigned_to=self.technician)
        WorkOrder.objects.unscoped().filter(pk=self.work_order.pk).update(
            status=WorkOrder.Status.TERMINADA,
            completed_by=self.technician,
            finished_at=timezone.now(),
        )
        self.client.force_login(self.supervisor)

    def test_verifying_is_a_confirmation_screen_before_it_is_a_post(self):
        response = self.client.get(reverse("workorder_verify", args=[self.work_order.pk]))

        assert response.status_code == 200
        assert "queda sellada como evidencia" in response.content.decode()

    def test_confirming_seals_the_work_order(self):
        response = self.client.post(reverse("workorder_verify", args=[self.work_order.pk]))

        self.work_order.refresh_from_db()
        assert response.status_code == 302
        assert self.work_order.status == WorkOrder.Status.VERIFICADA
        assert self.work_order.verified_by_id == self.supervisor.pk

    def test_a_technician_cannot_reach_the_verify_screen(self):
        self.client.force_login(self.technician)

        response = self.client.get(reverse("workorder_verify", args=[self.work_order.pk]))

        assert response.status_code == 403

    def test_cancelling_requires_a_reason(self):
        response = self.client.post(
            reverse("workorder_cancel", args=[self.work_order.pk]), {"reason": ""}
        )

        self.work_order.refresh_from_db()
        assert response.status_code == 200
        assert self.work_order.status == WorkOrder.Status.TERMINADA

    def test_cancelling_with_a_reason_stores_it(self):
        response = self.client.post(
            reverse("workorder_cancel", args=[self.work_order.pk]),
            {"reason": "El equipo se dio de baja"},
        )

        self.work_order.refresh_from_db()
        assert response.status_code == 302
        assert self.work_order.status == WorkOrder.Status.CANCELADA
        assert self.work_order.cancel_reason == "El equipo se dio de baja"


class CorrectiveWorkOrderTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.client.force_login(self.supervisor)
        self.url = reverse("workorder_corrective_create", args=[self.asset.pk])

    def _payload(self, **overrides):
        payload = {
            "priority": "alta",
            "due_date": "",
            "assigned_to": "",
            "failure_description": "La banda transportadora patina.",
            "checklist_template": "",
        }
        payload.update(overrides)
        return payload

    def test_a_supervisor_creates_an_unassigned_corrective_work_order(self):
        response = self.client.post(self.url, self._payload())

        work_order = WorkOrder.objects.unscoped().get(asset=self.asset)
        assert response.status_code == 302
        assert work_order.type == WorkOrder.Type.CORRECTIVO
        assert work_order.origin == WorkOrder.Origin.MANUAL
        assert work_order.status == WorkOrder.Status.ABIERTA
        assert work_order.company_id == self.company.pk

    def test_assigning_at_creation_starts_it_as_asignada(self):
        self.client.post(self.url, self._payload(assigned_to=self.technician.pk))

        work_order = WorkOrder.objects.unscoped().get(asset=self.asset)
        assert work_order.status == WorkOrder.Status.ASIGNADA
        assert work_order.assigned_to_id == self.technician.pk

    def test_a_failure_description_is_required(self):
        response = self.client.post(self.url, self._payload(failure_description=""))

        assert response.status_code == 200
        assert WorkOrder.objects.unscoped().filter(asset=self.asset).count() == 0

    def test_choosing_a_template_snapshots_it(self):
        template = create_flowpac_inspeccion_semanal(company=self.company)

        self.client.post(self.url, self._payload(checklist_template=template.pk))

        work_order = WorkOrder.objects.unscoped().get(asset=self.asset)
        assert work_order.checklist_template_id == template.pk
        assert len(list(services.checklist_items(work_order))) == 3

    def test_a_corrective_without_a_template_is_born_without_a_checklist(self):
        self.client.post(self.url, self._payload())

        work_order = WorkOrder.objects.unscoped().get(asset=self.asset)
        assert list(services.checklist_items(work_order)) == []

    def test_the_template_is_prefilled_from_the_assets_category(self):
        matching = ChecklistTemplateFactory(
            company=self.company, category=self.asset.category, name="De esta categoría"
        )
        ChecklistTemplateFactory(company=self.company, name="De otra categoría")

        form = self.client.get(self.url).context["form"]

        assert form.fields["checklist_template"].initial == matching

    def test_a_technician_may_report_but_not_assign(self):
        self.client.force_login(self.technician)

        response = self.client.get(self.url)
        assert "assigned_to" not in response.context["form"].fields

        self.client.post(self.url, self._payload(assigned_to=self.technician.pk))
        work_order = WorkOrder.objects.unscoped().get(asset=self.asset)
        assert work_order.assigned_to_id is None
        assert work_order.status == WorkOrder.Status.ABIERTA

    def test_office_staff_cannot_report_a_failure(self):
        self.client.force_login(StaffUserFactory(company=self.company))

        response = self.client.post(self.url, self._payload())

        assert response.status_code == 403
        assert WorkOrder.objects.unscoped().filter(asset=self.asset).count() == 0

    def test_another_companys_checklists_are_not_offered(self):
        mine = ChecklistTemplateFactory(company=self.company)
        theirs = ChecklistTemplateFactory(company=CompanyFactory())

        form = self.client.get(self.url).context["form"]

        assert mine in form.fields["checklist_template"].queryset
        assert theirs not in form.fields["checklist_template"].queryset


class AssetDetailIntegrationTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.client.force_login(SupervisorUserFactory(company=self.company))
        self.url = reverse("asset_detail", args=[self.asset.pk])

    def test_the_asset_page_lists_its_work_orders(self):
        WorkOrderFactory(asset=self.asset, status=WorkOrder.Status.ABIERTA)

        content = self.client.get(self.url).content.decode()

        assert "Órdenes de trabajo" in content
        assert reverse("workorder_corrective_create", args=[self.asset.pk]) in content

    def test_the_empty_state_replaces_the_old_coming_soon_placeholder(self):
        content = self.client.get(self.url).content.decode()

        assert "Este equipo no tiene órdenes de trabajo." in content
        assert "próximamente" not in content

    def test_office_staff_are_not_offered_the_report_button(self):
        self.client.force_login(StaffUserFactory(company=self.company))

        content = self.client.get(self.url).content.decode()

        assert reverse("workorder_corrective_create", args=[self.asset.pk]) not in content


class WorkOrderChecklistItemQuerysetTests(TestCase):
    """A guard against a regression that would be silent: the execution screen
    must read items through the scoped manager, so another company's item
    cannot be reached by primary key."""

    def test_an_item_of_another_companys_work_order_is_not_visible(self):
        company = CompanyFactory()
        other_company = CompanyFactory()
        technician = TechnicianUserFactory(company=company)
        mine = WorkOrderFactory(
            asset=AssetFactory(company=company),
            status=WorkOrder.Status.EN_PROGRESO,
            assigned_to=technician,
        )
        theirs = WorkOrderFactory(asset=AssetFactory(company=other_company))
        foreign_item = WorkOrderChecklistItemFactory(work_order=theirs, order=1)

        self.client.force_login(technician)
        response = self.client.post(
            reverse("workorder_item_save", args=[mine.pk, foreign_item.pk]), {"result": "ok"}
        )

        assert response.status_code == 404
        foreign_item.refresh_from_db()
        assert foreign_item.result == ""
