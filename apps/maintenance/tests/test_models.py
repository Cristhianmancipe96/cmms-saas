"""Acceptance criterion 5 (readings never go backwards) and the database
guarantees the scheduler relies on."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from apps.accounts.tests.factories import CompanyFactory, TechnicianUserFactory
from apps.assets.tests.factories import AssetFactory
from apps.maintenance.models import MaintenancePlan, MeterReading
from apps.maintenance.tests.factories import (
    MaintenancePlanFactory,
    MeterPlanFactory,
    MeterReadingFactory,
)
from apps.workorders.models import WorkOrder
from apps.workorders.tests.factories import WorkOrderFactory


class MeterReadingMonotonicityTests(TestCase):
    """Acceptance criterion 5: an hour meter never runs backwards."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("500.00"))

    def test_a_lower_reading_is_rejected(self):
        with pytest.raises(ValidationError):
            MeterReadingFactory(asset=self.asset, reading_hours=Decimal("499.00"))

    def test_the_rejection_message_is_in_spanish_and_names_both_values(self):
        with pytest.raises(ValidationError) as error:
            MeterReadingFactory(asset=self.asset, reading_hours=Decimal("499.00"))

        message = " ".join(error.value.messages)
        assert message == (
            "La lectura (499 h) no puede ser menor que la última registrada (500 h)."
        )

    def test_an_equal_reading_is_accepted(self):
        """Non-decreasing, not strictly increasing: a machine that did not run
        reads the same number the next day."""
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("500.00"))

        assert MeterReading.objects.unscoped().filter(asset=self.asset).count() == 2

    def test_a_higher_reading_is_accepted(self):
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("500.25"))

        assert MeterReading.objects.unscoped().filter(asset=self.asset).count() == 2

    def test_the_guard_is_per_asset(self):
        other_asset = AssetFactory(company=self.company)

        MeterReadingFactory(asset=other_asset, reading_hours=Decimal("10.00"))

        assert MeterReading.objects.unscoped().filter(asset=other_asset).count() == 1

    def test_the_guard_holds_at_the_model_layer(self):
        """Deliberately bypassing every form: a shell, the admin or a
        management command must not be able to write a backwards reading."""
        reading = MeterReading(
            company=self.company, asset=self.asset, reading_hours=Decimal("1.00")
        )

        with pytest.raises(ValidationError):
            reading.save()

    def test_saving_an_existing_reading_again_is_not_a_violation(self):
        """The row must not be compared against itself."""
        reading = MeterReading.objects.unscoped().filter(asset=self.asset).first()

        reading.save()

        assert MeterReading.objects.unscoped().filter(asset=self.asset).count() == 1


class WorkOrderUniquenessTests(TestCase):
    """CLAUDE.md rule 5 as a database guarantee, not a convention."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.plan = MaintenancePlanFactory(company=self.company, asset=self.asset)

    def test_two_work_orders_for_the_same_plan_and_date_are_impossible(self):
        WorkOrderFactory(asset=self.asset, plan=self.plan, due_date=self.plan.next_due_date)

        with pytest.raises(IntegrityError), transaction.atomic():
            WorkOrderFactory(asset=self.asset, plan=self.plan, due_date=self.plan.next_due_date)

    def test_the_same_plan_on_different_dates_is_fine(self):
        WorkOrderFactory(asset=self.asset, plan=self.plan, due_date="2026-01-01")
        WorkOrderFactory(asset=self.asset, plan=self.plan, due_date="2026-01-08")

        assert WorkOrder.objects.unscoped().filter(plan=self.plan).count() == 2

    def test_corrective_work_orders_without_a_plan_are_never_deduplicated(self):
        """NULLs are distinct in a Postgres unique index, so the constraint
        only ever binds plan-generated rows."""
        WorkOrderFactory(asset=self.asset, plan=None, due_date="2026-01-01")
        WorkOrderFactory(asset=self.asset, plan=None, due_date="2026-01-01")

        assert WorkOrder.objects.unscoped().filter(plan__isnull=True).count() == 2


class PlanConstraintTests(TestCase):
    """A plan the scheduler cannot act on is rejected by the database, not
    only by the form."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)

    def test_a_calendar_plan_without_an_interval_is_rejected(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            MaintenancePlanFactory(company=self.company, asset=self.asset, interval_days=None)

    def test_a_calendar_plan_without_a_due_date_is_rejected(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            MaintenancePlanFactory(company=self.company, asset=self.asset, next_due_date=None)

    def test_a_meter_plan_without_an_hour_interval_is_rejected(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            MeterPlanFactory(company=self.company, asset=self.asset, meter_interval_hours=None)

    def test_a_zero_day_interval_is_rejected(self):
        """Without this the catch-up loop would never terminate."""
        with pytest.raises(IntegrityError), transaction.atomic():
            MaintenancePlanFactory(company=self.company, asset=self.asset, interval_days=0)


class PlanDisplayTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)

    def test_preset_intervals_read_as_their_period_name(self):
        plan = MaintenancePlanFactory(company=self.company, asset=self.asset, interval_days=30)

        assert plan.frequency_label == "Mensual"

    def test_custom_intervals_read_as_days(self):
        plan = MaintenancePlanFactory(company=self.company, asset=self.asset, interval_days=45)

        assert plan.frequency_label == "Cada 45 días"

    def test_meter_plans_read_as_hours_without_trailing_zeros(self):
        plan = MeterPlanFactory(
            company=self.company, asset=self.asset, meter_interval_hours=Decimal("250.00")
        )

        assert plan.frequency_label == "Cada 250 h"


class PlanDeletionTests(TestCase):
    """Work orders are audit evidence: the plan that scheduled them cannot be
    deleted out from under them (CLAUDE.md rule 4)."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.plan = MaintenancePlanFactory(company=self.company, asset=self.asset)

    def test_a_plan_without_work_orders_deletes(self):
        self.plan.delete()

        assert MaintenancePlan.objects.unscoped().filter(pk=self.plan.pk).count() == 0

    def test_a_plan_with_work_orders_is_protected(self):
        WorkOrderFactory(asset=self.asset, plan=self.plan, due_date=self.plan.next_due_date)

        with pytest.raises(ProtectedError):
            self.plan.delete()


class MeterReadingAuthorshipTests(TestCase):
    def test_a_reading_records_who_took_it(self):
        company = CompanyFactory()
        asset = AssetFactory(company=company)
        technician = TechnicianUserFactory(company=company)

        reading = MeterReadingFactory(
            asset=asset, reading_hours=Decimal("12.00"), recorded_by=technician
        )

        assert reading.recorded_by_id == technician.pk
        assert reading.source == MeterReading.Source.MANUAL
