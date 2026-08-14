"""Checklist-version resolution and the due-state annotation the plan
screens render."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.tests.factories import CompanyFactory
from apps.assets.tests.factories import AssetFactory
from apps.checklists.tests.factories import ChecklistTemplateFactory
from apps.maintenance import services
from apps.maintenance.tests.factories import (
    MaintenancePlanFactory,
    MeterPlanFactory,
    MeterReadingFactory,
)


class ResolveChecklistTemplateTests(TestCase):
    """"Latest active version resolved at WO-creation time": a plan stores a
    pointer into a lineage, not the answer."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.v1 = ChecklistTemplateFactory(company=self.company, version=1)

    def _plan(self, template):
        return MaintenancePlanFactory(
            company=self.company, asset=self.asset, checklist_template=template
        )

    def test_an_unforked_template_resolves_to_itself(self):
        assert services.resolve_checklist_template(self._plan(self.v1)) == self.v1

    def test_a_plan_without_a_template_resolves_to_none(self):
        assert services.resolve_checklist_template(self._plan(None)) is None

    def test_a_forked_lineage_resolves_to_the_newest_active_version(self):
        """Brief 03 forks a locked template into v2 and retires v1. A plan
        still pointing at v1 must schedule with v2."""
        self.v1.is_active = False
        self.v1.save(update_fields=["is_active"])
        v2 = ChecklistTemplateFactory(
            company=self.company, version=2, parent=self.v1, is_active=True
        )

        assert services.resolve_checklist_template(self._plan(self.v1)) == v2

    def test_resolution_walks_the_whole_chain(self):
        self.v1.is_active = False
        self.v1.save(update_fields=["is_active"])
        v2 = ChecklistTemplateFactory(
            company=self.company, version=2, parent=self.v1, is_active=False
        )
        v3 = ChecklistTemplateFactory(company=self.company, version=3, parent=v2, is_active=True)

        assert services.resolve_checklist_template(self._plan(self.v1)) == v3

    def test_a_fully_deactivated_lineage_resolves_to_none(self):
        self.v1.is_active = False
        self.v1.save(update_fields=["is_active"])

        assert services.resolve_checklist_template(self._plan(self.v1)) is None


class DueStateTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.today = timezone.localdate()

    def _state(self, plan):
        return services.annotate_due_state([plan], today=self.today)[0].due_state

    def test_a_past_due_date_is_overdue(self):
        plan = MaintenancePlanFactory(
            company=self.company, asset=self.asset, next_due_date=self.today - timedelta(days=1)
        )

        assert self._state(plan) == "vencido"

    def test_a_due_date_within_a_week_is_due_soon(self):
        plan = MaintenancePlanFactory(
            company=self.company, asset=self.asset, next_due_date=self.today + timedelta(days=7)
        )

        assert self._state(plan) == "por_vencer"

    def test_a_distant_due_date_is_up_to_date(self):
        plan = MaintenancePlanFactory(
            company=self.company, asset=self.asset, next_due_date=self.today + timedelta(days=30)
        )

        assert self._state(plan) == "al_dia"

    def test_an_inactive_plan_reports_inactive_whatever_its_date(self):
        plan = MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            is_active=False,
            next_due_date=self.today - timedelta(days=90),
        )

        assert self._state(plan) == "inactivo"

    def test_a_meter_plan_without_readings_says_so(self):
        plan = MeterPlanFactory(company=self.company, asset=self.asset)

        assert self._state(plan) == "sin_lecturas"

    def test_a_meter_plan_past_its_interval_is_overdue(self):
        plan = MeterPlanFactory(
            company=self.company, asset=self.asset, meter_interval_hours=Decimal("100.00")
        )
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("120.00"))

        assert self._state(plan) == "vencido"

    def test_a_meter_plan_near_its_interval_is_due_soon(self):
        plan = MeterPlanFactory(
            company=self.company, asset=self.asset, meter_interval_hours=Decimal("100.00")
        )
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("95.00"))

        assert self._state(plan) == "por_vencer"

    def test_the_label_is_spanish(self):
        plan = MaintenancePlanFactory(
            company=self.company, asset=self.asset, next_due_date=self.today - timedelta(days=1)
        )

        assert services.annotate_due_state([plan], today=self.today)[0].due_label == "Vencido"

    def test_meter_readings_are_fetched_in_one_query_for_the_whole_list(self):
        """Guards the plan list against an N+1 as a company adds machines."""
        plans = [
            MeterPlanFactory(company=self.company, asset=AssetFactory(company=self.company))
            for _ in range(3)
        ]
        for plan in plans:
            MeterReadingFactory(asset=plan.asset, reading_hours=Decimal("10.00"))

        with self.assertNumQueries(1):
            services.annotate_due_state(plans, today=self.today)


class LatestReadingTests(TestCase):
    def test_returns_none_without_readings(self):
        asset = AssetFactory()

        assert services.latest_reading_hours(asset.pk) is None

    def test_returns_the_highest_reading(self):
        asset = AssetFactory()
        MeterReadingFactory(asset=asset, reading_hours=Decimal("10.00"))
        MeterReadingFactory(asset=asset, reading_hours=Decimal("42.50"))

        assert services.latest_reading_hours(asset.pk) == Decimal("42.50")

    def test_works_with_no_tenant_context_set(self):
        """A cron job has no request middleware; a scoped read here would
        silently return None and the plan would never fire."""
        asset = AssetFactory()
        MeterReadingFactory(asset=asset, reading_hours=Decimal("7.00"))

        assert services.latest_reading_hours(asset.pk) == Decimal("7.00")
