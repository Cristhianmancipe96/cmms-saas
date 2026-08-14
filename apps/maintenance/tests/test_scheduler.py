"""Acceptance criteria 1, 2, 3, 4, 6 and 7 of brief 04."""

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.tests.factories import CompanyFactory, TechnicianUserFactory
from apps.assets.models import Asset
from apps.assets.tests.factories import AssetFactory
from apps.core.tenancy import current_company_id
from apps.maintenance import services
from apps.maintenance.models import MaintenancePlan
from apps.maintenance.tests.factories import (
    MaintenancePlanFactory,
    MeterPlanFactory,
    MeterReadingFactory,
)
from apps.workorders.models import WorkOrder


def work_orders(**filters):
    """Every work order in the database, tenant scoping deliberately off:
    these tests assert across companies on purpose."""
    return WorkOrder.objects.unscoped().filter(**filters).order_by("due_date")


def run_command(**options) -> str:
    out = StringIO()
    call_command("generate_work_orders", stdout=out, **options)
    return out.getvalue()


class RunTwiceTests(TestCase):
    """Acceptance criterion 1: the command is idempotent — literally run
    twice, the second run creates nothing.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.plan = MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            interval_days=7,
            next_due_date=timezone.localdate() - timedelta(days=20),
        )

    def test_second_run_creates_no_rows(self):
        run_command()
        after_first = work_orders().count()

        run_command()

        assert after_first == 3
        assert work_orders().count() == after_first

    def test_second_run_reports_nothing_created(self):
        run_command()

        output = run_command()

        assert "created: 0" in output

    def test_idempotency_survives_a_crash_between_the_work_order_and_the_plan(self):
        """The structural half of criterion 1.

        Advancing `next_due_date` is what stops the *normal* second run, so
        this test throws that away: it rewinds the plan to where it was
        before the first run, simulating a crash after the work orders were
        written but before the plan was saved. Only `UNIQUE(plan, due_date)`
        + `get_or_create` can carry this — and it does: zero new rows.
        """
        run_command()
        created = work_orders().count()
        MaintenancePlan.objects.unscoped().filter(pk=self.plan.pk).update(
            next_due_date=timezone.localdate() - timedelta(days=20)
        )

        output = run_command()

        assert work_orders().count() == created
        assert "created: 0" in output
        assert "skipped-existing: 3" in output


class CatchUpTests(TestCase):
    """Acceptance criterion 2: a late weekly plan generates every missed work
    order, with its real historical date, and ends up due in the future.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.today = timezone.localdate()

    def test_three_weeks_late_generates_the_three_missed_work_orders(self):
        plan = MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            interval_days=7,
            next_due_date=self.today - timedelta(days=20),
        )

        run_command()

        due_dates = list(work_orders(plan=plan).values_list("due_date", flat=True))
        plan.refresh_from_db()
        assert due_dates == [
            self.today - timedelta(days=20),
            self.today - timedelta(days=13),
            self.today - timedelta(days=6),
        ]
        assert plan.next_due_date == self.today + timedelta(days=1)
        assert plan.next_due_date > self.today

    def test_catch_up_advances_from_the_due_date_not_from_today(self):
        """No drift: the series keeps its original weekday even though the
        scheduler was down for three weeks."""
        plan = MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            interval_days=7,
            next_due_date=self.today - timedelta(days=20),
        )

        run_command()

        due_dates = list(work_orders(plan=plan).values_list("due_date", flat=True))
        for earlier, later in zip(due_dates, due_dates[1:], strict=False):
            assert (later - earlier).days == 7

    def test_an_occurrence_due_exactly_today_is_generated(self):
        """The horizon is inclusive (`next_due_date <= today + horizon`), so a
        plan exactly 21 days late also produces today's work order — three
        missed plus the one due now."""
        plan = MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            interval_days=7,
            next_due_date=self.today - timedelta(days=21),
        )

        run_command()

        due_dates = list(work_orders(plan=plan).values_list("due_date", flat=True))
        assert due_dates[-1] == self.today
        assert len(due_dates) == 4

    def test_a_future_plan_generates_nothing_until_the_horizon_reaches_it(self):
        plan = MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            interval_days=7,
            next_due_date=self.today + timedelta(days=3),
        )

        run_command()
        assert work_orders(plan=plan).count() == 0

        run_command(horizon=5)
        assert work_orders(plan=plan).count() == 1


class MonthLengthTests(TestCase):
    """Acceptance criterion 3: the named periods advance by calendar months,
    so Jan 31 lands on Feb 28 instead of drifting to Mar 2.
    """

    def test_monthly_preset_clamps_to_the_shorter_month(self):
        assert services.advance_due_date(date(2026, 1, 31), 30) == date(2026, 2, 28)

    def test_monthly_preset_clamps_to_february_29_in_a_leap_year(self):
        assert services.advance_due_date(date(2024, 1, 31), 30) == date(2024, 2, 29)

    def test_annual_preset_keeps_the_same_calendar_day(self):
        assert services.advance_due_date(date(2026, 1, 31), 365) == date(2027, 1, 31)

    def test_annual_preset_across_a_leap_day(self):
        assert services.advance_due_date(date(2024, 2, 29), 365) == date(2025, 2, 28)

    def test_quarterly_and_semiannual_presets_advance_by_months(self):
        assert services.advance_due_date(date(2026, 1, 15), 90) == date(2026, 4, 15)
        assert services.advance_due_date(date(2026, 1, 15), 180) == date(2026, 7, 15)

    def test_non_preset_intervals_stay_literal_days(self):
        assert services.advance_due_date(date(2026, 1, 31), 7) == date(2026, 2, 7)
        assert services.advance_due_date(date(2026, 1, 31), 45) == date(2026, 3, 17)

    def test_a_monthly_plan_catches_up_across_month_lengths(self):
        company = CompanyFactory()
        asset = AssetFactory(company=company)
        plan = MaintenancePlanFactory(
            company=company, asset=asset, interval_days=30, next_due_date=date(2026, 1, 31)
        )

        services.generate_for_company(company, today=date(2026, 2, 28))

        plan.refresh_from_db()
        assert list(work_orders(plan=plan).values_list("due_date", flat=True)) == [
            date(2026, 1, 31),
            date(2026, 2, 28),
        ]
        assert plan.next_due_date == date(2026, 3, 28)


class MeterPlanTests(TestCase):
    """Acceptance criterion 4: 95 h -> 210 h on a 100 h interval is exactly
    one work order, and the next one waits for another full interval.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.plan = MeterPlanFactory(
            company=self.company, asset=self.asset, meter_interval_hours=Decimal("100.00")
        )
        self.today = date(2026, 3, 1)

    def _run(self, day_offset=0):
        return services.generate_for_company(
            self.company, today=self.today + timedelta(days=day_offset)
        )

    def test_below_the_interval_generates_nothing(self):
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("95.00"))

        self._run()

        assert work_orders(plan=self.plan).count() == 0

    def test_crossing_the_interval_generates_exactly_one_work_order(self):
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("95.00"))
        self._run()
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("210.00"))

        self._run()

        assert work_orders(plan=self.plan).count() == 1
        self.plan.refresh_from_db()
        assert self.plan.hours_at_last_generated_wo == Decimal("210.00")

    def test_the_next_one_waits_for_another_full_interval(self):
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("210.00"))
        self._run()

        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("309.00"))
        self._run(day_offset=1)
        assert work_orders(plan=self.plan).count() == 1

        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("310.00"))
        self._run(day_offset=2)
        assert work_orders(plan=self.plan).count() == 2

    def test_a_plan_with_no_readings_generates_nothing(self):
        self._run()

        assert work_orders(plan=self.plan).count() == 0

    def test_two_crossings_on_the_same_day_share_one_work_order(self):
        """`UNIQUE(plan, due_date)` caps a meter plan at one work order per
        day. Physically unreachable (100 h of machine time cannot elapse in
        24 h), and the right answer anyway: the machine gets serviced once.
        The run reports it as skipped-existing rather than swallowing it.
        """
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("100.00"))
        self._run()
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("250.00"))

        result = self._run()

        assert work_orders(plan=self.plan).count() == 1
        assert result.created == 0
        assert result.skipped_existing == 1


class SkippedPlanTests(TestCase):
    """Acceptance criterion 6: inactive plans and retired assets generate
    nothing at all.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.today = timezone.localdate()

    def test_an_inactive_plan_generates_nothing(self):
        plan = MaintenancePlanFactory(
            company=self.company,
            asset=AssetFactory(company=self.company),
            is_active=False,
            next_due_date=self.today - timedelta(days=30),
        )

        run_command()

        assert work_orders(plan=plan).count() == 0
        plan.refresh_from_db()
        assert plan.next_due_date == self.today - timedelta(days=30)

    def test_a_plan_on_a_retired_asset_generates_nothing(self):
        retired = AssetFactory(company=self.company, status=Asset.Status.DADO_DE_BAJA)
        plan = MaintenancePlanFactory(
            company=self.company, asset=retired, next_due_date=self.today - timedelta(days=30)
        )

        run_command()

        assert work_orders(plan=plan).count() == 0

    def test_an_inactive_meter_plan_generates_nothing(self):
        asset = AssetFactory(company=self.company)
        plan = MeterPlanFactory(company=self.company, asset=asset, is_active=False)
        MeterReadingFactory(asset=asset, reading_hours=Decimal("500.00"))

        run_command()

        assert work_orders(plan=plan).count() == 0

    def test_active_plans_next_to_skipped_ones_still_run(self):
        MaintenancePlanFactory(
            company=self.company,
            asset=AssetFactory(company=self.company),
            is_active=False,
            next_due_date=self.today,
        )
        live = MaintenancePlanFactory(
            company=self.company,
            asset=AssetFactory(company=self.company),
            next_due_date=self.today,
        )

        run_command()

        assert work_orders(plan=live).count() == 1


class CommandTenantIsolationTests(TestCase):
    """Acceptance criterion 7, command half: the run iterates per company and
    company A's context never reaches company B.
    """

    def setUp(self):
        self.today = timezone.localdate()
        self.company_a = CompanyFactory(name="Empresa A")
        self.company_b = CompanyFactory(name="Empresa B")
        self.asset_a = AssetFactory(company=self.company_a)
        self.asset_b = AssetFactory(company=self.company_b)
        self.plan_a = MaintenancePlanFactory(
            company=self.company_a,
            asset=self.asset_a,
            next_due_date=self.today - timedelta(days=7),
        )
        self.plan_b = MaintenancePlanFactory(
            company=self.company_b,
            asset=self.asset_b,
            next_due_date=self.today - timedelta(days=7),
        )

    def test_every_work_order_belongs_to_its_own_plans_company(self):
        run_command()

        for work_order in work_orders():
            assert work_order.company_id == work_order.plan.company_id
            assert work_order.company_id == work_order.asset.company_id

    def test_running_one_company_leaves_the_other_untouched(self):
        services.generate_for_company(self.company_a, today=self.today)

        assert work_orders(plan=self.plan_a).count() == 2
        assert work_orders(plan=self.plan_b).count() == 0
        self.plan_b.refresh_from_db()
        assert self.plan_b.next_due_date == self.today - timedelta(days=7)

    def test_each_company_is_reported_separately(self):
        output = run_command()

        assert "Empresa A: plans evaluated: 1" in output
        assert "Empresa B: plans evaluated: 1" in output
        assert "TOTAL — plans evaluated: 2 · created: 4 · skipped-existing: 0" in output

    def test_the_tenant_context_is_reset_after_the_run(self):
        """A leaked contextvar would silently scope the *next* job in the same
        process to the last company the scheduler happened to touch."""
        run_command()

        assert current_company_id.get() is None

    def test_an_inactive_company_is_skipped(self):
        self.company_b.is_active = False
        self.company_b.save(update_fields=["is_active"])

        run_command()

        assert work_orders(plan=self.plan_b).count() == 0
        assert work_orders(plan=self.plan_a).count() == 2


class WorkOrderContentTests(TestCase):
    """What a generated work order actually carries over from its plan."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)

    def test_generated_work_order_copies_plan_defaults(self):
        plan = MaintenancePlanFactory(
            company=self.company,
            asset=self.asset,
            kind=MaintenancePlan.Kind.INSPECCION,
            default_assignee=self.technician,
            next_due_date=timezone.localdate(),
        )

        run_command()

        work_order = work_orders(plan=plan).get()
        assert work_order.type == WorkOrder.Type.INSPECCION
        assert work_order.origin == WorkOrder.Origin.PLAN
        assert work_order.status == WorkOrder.Status.ABIERTA
        assert work_order.assigned_to_id == self.technician.pk
        assert work_order.asset_id == self.asset.pk

    def test_lubrication_and_calibration_plans_produce_preventive_work_orders(self):
        for kind in (MaintenancePlan.Kind.LUBRICACION, MaintenancePlan.Kind.CALIBRACION):
            with self.subTest(kind=kind):
                plan = MaintenancePlanFactory(
                    company=self.company,
                    asset=AssetFactory(company=self.company),
                    kind=kind,
                    next_due_date=timezone.localdate(),
                )
                services.generate_for_company(self.company, today=timezone.localdate())
                assert work_orders(plan=plan).get().type == WorkOrder.Type.PREVENTIVO
