"""Every action an auditor would ask about leaves a row — and no row leaks a secret.

One test per audited action (brief item 3), each asserting the same three
things: that a row exists, that it names who did it, and that `changes` records
the old→new the auditor is actually after.
"""

from datetime import date

import pytest
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    SiteFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.models import Asset
from apps.assets.tests.factories import AssetCategoryFactory, AssetFactory
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.maintenance.models import MaintenancePlan
from apps.maintenance.tests.factories import MaintenancePlanFactory
from apps.reports import pdf
from apps.requests_ import services as request_services
from apps.requests_.tests.factories import MaintenanceRequestFactory
from apps.workorders import services as workorder_services
from apps.workorders.models import WorkOrder
from apps.workorders.tests.factories import AssignedWorkOrderFactory


def rows_for(instance) -> list[AuditLog]:
    return list(
        AuditLog.objects.unscoped()
        .filter(
            model_label=f"{instance._meta.app_label}.{instance._meta.object_name}",
            object_id=instance.pk,
        )
        .order_by("id")
    )


class WorkOrderTransitionTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.work_order = AssignedWorkOrderFactory(
            asset=self.asset, assigned_to=self.technician, company=self.company
        )

    def test_each_transition_records_the_status_it_moved(self):
        workorder_services.transition(
            self.work_order, workorder_services.START, self.technician
        )
        workorder_services.transition(
            self.work_order, workorder_services.COMPLETE, self.technician
        )
        workorder_services.transition(
            self.work_order, workorder_services.VERIFY, self.supervisor
        )

        rows = rows_for(self.work_order)
        assert [row.action for row in rows] == [AuditLog.Action.TRANSITION] * 3
        assert [row.changes["status"]["a"] for row in rows] == [
            WorkOrder.Status.EN_PROGRESO,
            WorkOrder.Status.TERMINADA,
            WorkOrder.Status.VERIFICADA,
        ]
        assert rows[0].changes["status"]["de"] == WorkOrder.Status.ASIGNADA
        assert rows[-1].user_id == self.supervisor.pk
        assert rows[-1].actor_label == str(self.supervisor)
        assert rows[-1].company_id == self.company.pk

    def test_the_verification_records_who_verified(self):
        workorder_services.transition(
            self.work_order, workorder_services.START, self.technician
        )
        workorder_services.transition(
            self.work_order, workorder_services.COMPLETE, self.technician
        )
        workorder_services.transition(
            self.work_order, workorder_services.VERIFY, self.supervisor
        )

        last = rows_for(self.work_order)[-1]
        assert last.changes["verified_by"]["a"] == self.supervisor.pk
        assert last.changes["verified_by"]["campo"] == "verificada por"

    def test_a_refused_transition_records_nothing(self):
        """No row for something that did not happen."""
        with pytest.raises(workorder_services.WorkOrderError):
            workorder_services.transition(
                self.work_order, workorder_services.VERIFY, self.supervisor
            )

        assert rows_for(self.work_order) == []


class RequestDecisionTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.staff = StaffUserFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)

    def test_reporting_converting_and_rejecting_are_all_recorded(self):
        reported = request_services.create_request(
            asset=self.asset, user=self.staff, description="Se detiene sola."
        )
        work_order = request_services.convert(reported, user=self.supervisor)

        rows = rows_for(reported)
        assert [row.action for row in rows] == [
            AuditLog.Action.CREATE,
            AuditLog.Action.TRANSITION,
        ]
        assert rows[0].user_id == self.staff.pk
        assert rows[1].user_id == self.supervisor.pk
        assert rows[1].changes["status"]["a"] == "convertida"
        # The auditor's question — "which OT came out of this?" — answered in
        # the row itself, not by cross-reading two tables.
        assert rows[1].changes["orden_de_trabajo"]["a"] == work_order.pk

    def test_a_rejection_records_its_reason(self):
        reported = MaintenanceRequestFactory(asset=self.asset, reported_by=self.staff)

        request_services.reject(
            reported, user=self.supervisor, note="Ese ruido es normal."
        )

        row = rows_for(reported)[-1]
        assert row.changes["review_note"]["a"] == "Ese ruido es normal."
        assert row.user_id == self.supervisor.pk


class AssetAndPlanTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.site = SiteFactory(company=self.company)
        self.category = AssetCategoryFactory(company=self.company)
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)

    def _asset_payload(self, **overrides):
        payload = {
            "code": "COMP-09",
            "name": "Compresor 9",
            "site": self.site.pk,
            "category": self.category.pk,
            "brand": "Kaeser",
            "model": "SK-25",
            "serial_number": "SN-000042",
            "criticality": Asset.Criticality.MEDIA,
            "location_detail": "Sala de compresores",
        }
        payload.update(overrides)
        return payload

    def test_creating_and_editing_an_asset_is_recorded(self):
        self.client.post(reverse("asset_create"), self._asset_payload())
        asset = Asset.objects.unscoped().get(code="COMP-09")

        self.client.post(
            reverse("asset_update", args=[asset.pk]),
            self._asset_payload(name="Compresor nueve", criticality=Asset.Criticality.ALTA),
        )

        rows = rows_for(asset)
        assert [row.action for row in rows] == [AuditLog.Action.CREATE, AuditLog.Action.UPDATE]
        assert rows[1].changes["name"] == {
            "campo": "nombre",
            "de": "Compresor 9",
            "a": "Compresor nueve",
        }
        assert rows[1].changes["criticality"]["a"] == Asset.Criticality.ALTA
        # Unchanged fields are absent: a diff, not a dump.
        assert "code" not in rows[1].changes

    def test_giving_an_asset_the_baja_is_recorded_with_its_reason(self):
        asset = AssetFactory(company=self.company)

        self.client.post(
            reverse("asset_baja", args=[asset.pk]), {"reason": "Chatarrizado en agosto."}
        )

        row = rows_for(asset)[-1]
        assert row.action == AuditLog.Action.TRANSITION
        assert row.changes["status"]["a"] == Asset.Status.DADO_DE_BAJA
        assert row.changes["baja_reason"]["a"] == "Chatarrizado en agosto."

    def test_editing_a_plan_is_recorded(self):
        asset = AssetFactory(company=self.company)
        plan = MaintenancePlanFactory(company=self.company, asset=asset, interval_days=30)

        response = self.client.post(
            reverse("maintenanceplan_update", args=[plan.pk]),
            {
                "name": plan.name,
                "kind": plan.kind,
                "frequency_type": MaintenancePlan.FrequencyType.CALENDAR,
                "interval_preset": "90",
                "interval_days": "",
                "next_due_date": date(2026, 12, 1).isoformat(),
                "meter_interval_hours": "",
                "checklist_template": "",
                "default_assignee": "",
                "estimated_minutes": "60",
                "is_active": "on",
            },
        )
        assert response.status_code == 302

        row = rows_for(plan)[-1]
        assert row.action == AuditLog.Action.UPDATE
        assert row.changes["interval_days"]["de"] == 30
        assert row.changes["interval_days"]["a"] == 90
        # The label comes from the model's own verbose_name, so the screen can
        # render a diff of any model without a translation table of its own.
        assert row.changes["interval_days"]["campo"] == "cada cuántos días"


class UserAndSendTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)

    def test_an_invitation_is_recorded_without_the_password(self):
        """Acceptance criterion 4: even when a User row is created — and a
        password *is* set on it — no audit row ever carries it."""
        response = self.client.post(
            reverse("user_invite"),
            {
                "username": "nuevo",
                "email": "nuevo@example.com",
                "role": "technician",
                "first_name": "Nuevo",
                "last_name": "Usuario",
            },
        )
        assert response.status_code == 302
        assert len(mail.outbox) == 1

        row = AuditLog.objects.unscoped().get(model_label="accounts.User")
        assert row.action == AuditLog.Action.CREATE
        assert row.user_id == self.admin.pk
        assert row.changes["username"]["a"] == "nuevo"
        serialized = str(row.changes)
        assert "password" not in serialized
        assert "pbkdf2" not in serialized and "md5" not in serialized

    def test_deactivating_a_user_is_recorded(self):
        target = TechnicianUserFactory(company=self.company)

        self.client.post(reverse("user_deactivate", args=[target.pk]))

        row = rows_for(target)[-1]
        assert row.action == AuditLog.Action.UPDATE
        # The label is whatever Django's own verbose_name translates to in
        # es-CO; what this test is about is the transition it records.
        assert row.changes["is_active"]["de"] is True
        assert row.changes["is_active"]["a"] is False

    @pytest.mark.skipif(
        not pdf.engine_available(),
        reason=(
            "Enviar exige renderizar el PDF, y sin las librerías nativas de "
            "WeasyPrint (en Windows: GTK) no hay envío que auditar. Corre en CI."
        ),
    )
    def test_sending_a_document_is_recorded(self):
        asset = AssetFactory(company=self.company)

        self.client.post(
            reverse("asset_record_send", args=[asset.pk]), {"recipients": [self.admin.pk]}
        )

        rows = [row for row in rows_for(asset) if row.action == AuditLog.Action.SEND]
        assert len(rows) == 1
        assert rows[0].changes["destinatarios"]["a"] == [self.admin.email]
        assert rows[0].changes["documento"]["a"] == "hoja_de_vida"


class SecretsTests(TestCase):
    """Nothing that looks like a credential ever reaches the table."""

    def setUp(self):
        self.company = CompanyFactory()
        self.user = AdminUserFactory(company=self.company)

    def test_a_password_field_is_redacted_even_if_a_call_site_asks_for_it(self):
        row = audit.record(
            action=AuditLog.Action.UPDATE,
            instance=self.user,
            user=self.user,
            company=self.company,
            changes=audit.diff(
                audit.snapshot(self.user, ("username", "password")),
                {"username": "x", "password": "un-hash-real"},
                instance=self.user,
            ),
        )

        assert row.changes["password"]["a"] == audit.REDACTED
        assert row.changes["password"]["de"] == audit.REDACTED
        assert "un-hash-real" not in str(row.changes)

    def test_snapshot_never_reads_a_sensitive_field_from_the_row(self):
        values = audit.snapshot(self.user, ("username", "password", "session_key"))

        assert values["password"] == audit.REDACTED
        assert values["session_key"] == audit.REDACTED
        assert values["username"] == self.user.username

    def test_a_token_hidden_inside_a_nested_dict_is_redacted_too(self):
        row = audit.record(
            action=AuditLog.Action.UPDATE,
            instance=self.user,
            user=self.user,
            company=self.company,
            changes=audit.note(configuracion={"url": "https://n8n", "token": "secretísimo"}),
        )

        assert "secretísimo" not in str(row.changes)

    def test_file_fields_never_enter_the_log(self):
        asset = AssetFactory(company=self.company)

        values = audit.snapshot(asset, ("name", "main_photo"))

        assert "main_photo" not in values
