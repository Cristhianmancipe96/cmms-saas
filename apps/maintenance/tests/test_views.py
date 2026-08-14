"""Plan CRUD, the meter quick-entry form and who is allowed to use them."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.checklists.tests.factories import ChecklistTemplateFactory
from apps.maintenance.models import MaintenancePlan, MeterReading
from apps.maintenance.tests.factories import (
    MaintenancePlanFactory,
    MeterPlanFactory,
    MeterReadingFactory,
)
from apps.workorders.tests.factories import WorkOrderFactory


def plan_payload(**overrides) -> dict:
    payload = {
        "name": "Preventivo semanal",
        "kind": MaintenancePlan.Kind.PREVENTIVO,
        "frequency_type": MaintenancePlan.FrequencyType.CALENDAR,
        "interval_preset": "7",
        "interval_days": "",
        "next_due_date": "2026-09-01",
        "meter_interval_hours": "",
        "checklist_template": "",
        "default_assignee": "",
        "estimated_minutes": "60",
        "is_active": "on",
    }
    payload.update(overrides)
    return payload


class PlanCreateTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)
        self.url = reverse("maintenanceplan_create", args=[self.asset.pk])

    def test_a_preset_interval_creates_a_calendar_plan(self):
        response = self.client.post(self.url, plan_payload())

        plan = MaintenancePlan.objects.unscoped().get(asset=self.asset)
        assert response.status_code == 302
        assert plan.interval_days == 7
        assert plan.frequency_type == MaintenancePlan.FrequencyType.CALENDAR
        assert plan.company_id == self.company.pk

    def test_a_custom_interval_is_accepted(self):
        self.client.post(
            self.url, plan_payload(interval_preset="custom", interval_days="45")
        )

        assert MaintenancePlan.objects.unscoped().get(asset=self.asset).interval_days == 45

    def test_a_custom_interval_without_a_number_is_rejected_in_spanish(self):
        response = self.client.post(
            self.url, plan_payload(interval_preset="custom", interval_days="")
        )

        assert response.status_code == 200
        assert "Indica cada cuántos días se repite el plan." in response.content.decode()
        assert MaintenancePlan.objects.unscoped().filter(asset=self.asset).count() == 0

    def test_a_calendar_plan_without_a_due_date_is_rejected_in_spanish(self):
        response = self.client.post(self.url, plan_payload(next_due_date=""))

        assert "Indica la fecha del próximo vencimiento." in response.content.decode()

    def test_a_meter_plan_clears_the_calendar_fields(self):
        self.client.post(
            self.url,
            plan_payload(
                frequency_type=MaintenancePlan.FrequencyType.METER,
                meter_interval_hours="250",
                interval_preset="7",
                next_due_date="2026-09-01",
            ),
        )

        plan = MaintenancePlan.objects.unscoped().get(asset=self.asset)
        assert plan.meter_interval_hours == Decimal("250.00")
        assert plan.interval_days is None
        assert plan.next_due_date is None

    def test_a_meter_plan_without_an_hour_interval_is_rejected_in_spanish(self):
        response = self.client.post(
            self.url,
            plan_payload(
                frequency_type=MaintenancePlan.FrequencyType.METER, meter_interval_hours=""
            ),
        )

        assert (
            "Indica cada cuántas horas de uso se debe hacer el mantenimiento."
            in response.content.decode()
        )

    def test_a_new_meter_plan_starts_from_the_machines_current_reading(self):
        """Otherwise a plan added to a machine already at 5.000 h would fire
        on the very next scheduler run."""
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("5000.00"))

        self.client.post(
            self.url,
            plan_payload(
                frequency_type=MaintenancePlan.FrequencyType.METER, meter_interval_hours="100"
            ),
        )

        plan = MaintenancePlan.objects.unscoped().get(asset=self.asset)
        assert plan.hours_at_last_generated_wo == Decimal("5000.00")

    def test_a_technician_cannot_create_a_plan(self):
        self.client.force_login(TechnicianUserFactory(company=self.company))

        response = self.client.post(self.url, plan_payload())

        assert response.status_code == 403
        assert MaintenancePlan.objects.unscoped().filter(asset=self.asset).count() == 0

    def test_a_supervisor_can_create_a_plan(self):
        self.client.force_login(SupervisorUserFactory(company=self.company))

        response = self.client.post(self.url, plan_payload())

        assert response.status_code == 302
        assert MaintenancePlan.objects.unscoped().filter(asset=self.asset).count() == 1


class PlanFormScopeTests(TestCase):
    """The dropdowns are tenant data too."""

    def setUp(self):
        self.company = CompanyFactory()
        self.other_company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.client.force_login(AdminUserFactory(company=self.company))

    def test_another_companys_checklists_are_not_offered(self):
        mine = ChecklistTemplateFactory(company=self.company, name="Checklist propio")
        theirs = ChecklistTemplateFactory(company=self.other_company, name="Checklist ajeno")

        form = self.client.get(
            reverse("maintenanceplan_create", args=[self.asset.pk])
        ).context["form"]

        assert mine in form.fields["checklist_template"].queryset
        assert theirs not in form.fields["checklist_template"].queryset

    def test_another_companys_technicians_are_not_offered(self):
        mine = TechnicianUserFactory(company=self.company)
        theirs = TechnicianUserFactory(company=self.other_company)

        form = self.client.get(
            reverse("maintenanceplan_create", args=[self.asset.pk])
        ).context["form"]

        assert mine in form.fields["default_assignee"].queryset
        assert theirs not in form.fields["default_assignee"].queryset


class PlanListTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.client.force_login(AdminUserFactory(company=self.company))
        self.today = timezone.localdate()
        self.url = reverse("maintenanceplan_list")

    def test_the_empty_state_explains_where_plans_come_from(self):
        content = self.client.get(self.url).content.decode()

        assert "Aún no hay planes de mantenimiento." in content

    def test_an_overdue_plan_is_highlighted_and_badged(self):
        MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            name="Engrase atrasado",
            next_due_date=self.today - timedelta(days=3),
        )

        content = self.client.get(self.url).content.decode()

        assert "vt-row--vencido" in content
        assert "vt-badge--vencido" in content
        assert "Vencido" in content

    def test_an_up_to_date_plan_is_not_highlighted(self):
        MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            next_due_date=self.today + timedelta(days=60),
        )

        content = self.client.get(self.url).content.decode()

        assert "vt-row--vencido" not in content
        assert "Al día" in content

    def test_an_inactive_plan_is_listed_but_muted(self):
        MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            name="Plan apagado",
            is_active=False,
            next_due_date=self.today - timedelta(days=3),
        )

        content = self.client.get(self.url).content.decode()

        assert "Plan apagado" in content
        assert "vt-row--inactivo" in content
        assert "vt-row--vencido" not in content

    def test_the_overdue_filter_keeps_only_overdue_plans(self):
        MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            name="Atrasado",
            next_due_date=self.today - timedelta(days=3),
        )
        MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            name="Al dia",
            next_due_date=self.today + timedelta(days=60),
        )

        content = self.client.get(self.url, {"estado": "vencidos"}).content.decode()

        assert "Atrasado" in content
        assert "Al dia" not in content

    def test_a_filter_with_no_results_says_so_differently(self):
        content = self.client.get(self.url, {"estado": "inactivos"}).content.decode()

        assert "No hay planes con esos filtros." in content

    def test_a_technician_can_read_the_list(self):
        self.client.force_login(TechnicianUserFactory(company=self.company))

        assert self.client.get(self.url).status_code == 200


class PlanDetailTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)

    def test_the_detail_shows_the_checklist_version_the_next_work_order_will_use(self):
        v1 = ChecklistTemplateFactory(company=self.company, name="Inspección", version=1)
        v1.is_active = False
        v1.save(update_fields=["is_active"])
        ChecklistTemplateFactory(company=self.company, version=2, parent=v1, is_active=True)
        plan = MaintenancePlanFactory(
            company=self.company, asset=self.asset, checklist_template=v1
        )

        response = self.client.get(reverse("maintenanceplan_detail", args=[plan.pk]))

        assert response.context["resolved_template"].version == 2

    def test_deactivating_a_plan_stops_it_generating(self):
        plan = MaintenancePlanFactory(company=self.company, asset=self.asset)

        self.client.post(reverse("maintenanceplan_toggle", args=[plan.pk]))

        plan.refresh_from_db()
        assert plan.is_active is False

    def test_deactivating_twice_reactivates(self):
        plan = MaintenancePlanFactory(company=self.company, asset=self.asset, is_active=False)

        self.client.post(reverse("maintenanceplan_toggle", args=[plan.pk]))

        plan.refresh_from_db()
        assert plan.is_active is True

    def test_a_technician_cannot_deactivate_a_plan(self):
        plan = MaintenancePlanFactory(company=self.company, asset=self.asset)
        self.client.force_login(TechnicianUserFactory(company=self.company))

        response = self.client.post(reverse("maintenanceplan_toggle", args=[plan.pk]))

        assert response.status_code == 403
        plan.refresh_from_db()
        assert plan.is_active is True

    def test_a_plan_without_work_orders_can_be_deleted(self):
        plan = MaintenancePlanFactory(company=self.company, asset=self.asset)

        response = self.client.post(reverse("maintenanceplan_delete", args=[plan.pk]))

        assert response.status_code == 302
        assert MaintenancePlan.objects.unscoped().filter(pk=plan.pk).count() == 0

    def test_a_plan_with_work_orders_cannot_be_deleted(self):
        plan = MaintenancePlanFactory(company=self.company, asset=self.asset)
        WorkOrderFactory(asset=self.asset, plan=plan, due_date=plan.next_due_date)

        response = self.client.post(
            reverse("maintenanceplan_delete", args=[plan.pk]), follow=True
        )

        assert MaintenancePlan.objects.unscoped().filter(pk=plan.pk).count() == 1
        assert "No se puede eliminar un plan que ya generó órdenes de trabajo." in (
            response.content.decode()
        )


class PlanUpdateTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.client.force_login(AdminUserFactory(company=self.company))

    def test_switching_a_calendar_plan_to_the_meter_starts_counting_from_now(self):
        plan = MaintenancePlanFactory(company=self.company, asset=self.asset)
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("5000.00"))

        self.client.post(
            reverse("maintenanceplan_update", args=[plan.pk]),
            plan_payload(
                frequency_type=MaintenancePlan.FrequencyType.METER, meter_interval_hours="100"
            ),
        )

        plan.refresh_from_db()
        assert plan.hours_at_last_generated_wo == Decimal("5000.00")

    def test_editing_a_meter_plan_does_not_reset_its_progress(self):
        plan = MeterPlanFactory(
            company=self.company,
            asset=self.asset,
            hours_at_last_generated_wo=Decimal("400.00"),
        )
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("480.00"))

        self.client.post(
            reverse("maintenanceplan_update", args=[plan.pk]),
            plan_payload(
                name="Nuevo nombre",
                frequency_type=MaintenancePlan.FrequencyType.METER,
                meter_interval_hours="100",
            ),
        )

        plan.refresh_from_db()
        assert plan.name == "Nuevo nombre"
        assert plan.hours_at_last_generated_wo == Decimal("400.00")


class MeterQuickEntryTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.client.force_login(self.technician)
        self.url = reverse("meterreading_create", args=[self.asset.pk])

    def test_a_technician_records_a_reading(self):
        response = self.client.post(self.url, {"reading_hours": "1250.5"})

        reading = MeterReading.objects.unscoped().get(asset=self.asset)
        assert response.status_code == 302
        assert reading.reading_hours == Decimal("1250.50")
        assert reading.recorded_by_id == self.technician.pk
        assert reading.company_id == self.company.pk

    def test_a_lower_reading_is_rejected_with_a_spanish_message(self):
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("500.00"))

        response = self.client.post(self.url, {"reading_hours": "400"}, follow=True)

        assert MeterReading.objects.unscoped().filter(asset=self.asset).count() == 1
        assert (
            "La lectura (400 h) no puede ser menor que la última registrada (500 h)."
            in response.content.decode()
        )

    def test_the_htmx_response_returns_the_refreshed_panel(self):
        response = self.client.post(
            self.url, {"reading_hours": "80"}, headers={"hx-request": "true"}
        )
        content = response.content.decode()

        assert response.status_code == 200
        assert 'id="panel-horometro"' in content
        assert "Lectura registrada." in content
        assert "80" in content

    def test_the_htmx_response_shows_the_error_next_to_the_field(self):
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("500.00"))

        response = self.client.post(
            self.url, {"reading_hours": "1"}, headers={"hx-request": "true"}
        )
        content = response.content.decode()

        assert 'aria-invalid="true"' in content
        assert "vt-field-error" in content
        assert "no puede ser menor" in content

    def test_office_staff_cannot_record_readings(self):
        self.client.force_login(StaffUserFactory(company=self.company))

        response = self.client.post(self.url, {"reading_hours": "10"})

        assert response.status_code == 403
        assert MeterReading.objects.unscoped().filter(asset=self.asset).count() == 0

    def test_the_form_is_not_reachable_by_get(self):
        assert self.client.get(self.url).status_code == 405


class AssetDetailIntegrationTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.client.force_login(AdminUserFactory(company=self.company))
        self.url = reverse("asset_detail", args=[self.asset.pk])

    def test_the_asset_page_lists_its_plans(self):
        MaintenancePlanFactory(company=self.company, asset=self.asset, name="Engrase mensual")

        content = self.client.get(self.url).content.decode()

        assert "Engrase mensual" in content
        assert "Mantenimiento preventivo" in content

    def test_the_asset_page_offers_to_create_the_first_plan(self):
        content = self.client.get(self.url).content.decode()

        assert "Aún no hay planes para este equipo." in content
        assert reverse("maintenanceplan_create", args=[self.asset.pk]) in content

    def test_the_asset_page_shows_the_meter_panel_with_the_latest_reading(self):
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("321.00"))

        content = self.client.get(self.url).content.decode()

        assert "Horómetro" in content
        assert "321" in content

    def test_a_technician_sees_the_meter_form_but_not_the_plan_button(self):
        self.client.force_login(TechnicianUserFactory(company=self.company))
        MeterPlanFactory(company=self.company, asset=self.asset)

        content = self.client.get(self.url).content.decode()

        assert "Registrar lectura" in content
        assert reverse("maintenanceplan_create", args=[self.asset.pk]) not in content

    def test_office_staff_sees_no_meter_form(self):
        self.client.force_login(StaffUserFactory(company=self.company))

        content = self.client.get(self.url).content.decode()

        assert "Registrar lectura" not in content
