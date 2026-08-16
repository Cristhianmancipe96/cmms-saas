"""Every KPI against the hand-computed scenario in `scenario.py`.

The assertions are exact numbers, never "does not explode": an indicator that
is merely non-crashing is an indicator nobody can defend in front of an
auditor. Each test names the arithmetic it is checking, so a failure says
which formula moved.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.tests.factories import CompanyFactory, SiteFactory
from apps.assets.models import Asset
from apps.assets.tests.factories import AssetFactory
from apps.kpis import queries
from apps.kpis.periods import Period
from apps.kpis.tests import scenario
from apps.workorders.models import WorkOrder
from apps.workorders.tests.factories import WorkOrderFactory


class MtbfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        cls.assets = scenario.build(cls.company)

    def test_fleet_mtbf_is_total_operating_time_over_total_failures(self):
        """(714 h + 720 h) ÷ 2 fallas = 717,00 h — not the average of the two
        per-asset MTBFs, which would be a different (and wrong) number."""
        result = queries.mtbf(self.company.pk, scenario.WINDOW)

        assert result.hours == scenario.EXPECTED_MTBF_FLEET
        assert result.failures == scenario.EXPECTED_FAILURES
        assert result.uptime_hours == scenario.EXPECTED_UPTIME_FLEET

    def test_mtbf_per_asset(self):
        result = queries.mtbf(self.company.pk, scenario.WINDOW)
        by_code = {row.code: row for row in result.by_asset}

        assert by_code["E-01"].hours == scenario.EXPECTED_MTBF_E1
        assert by_code["E-01"].failures == 2
        assert by_code["E-01"].uptime_hours == Decimal("714.00")

    def test_an_asset_without_failures_has_no_mtbf(self):
        """Undefined, not infinite and not zero: «—» on screen."""
        result = queries.mtbf(self.company.pk, scenario.WINDOW)
        by_code = {row.code: row for row in result.by_asset}

        assert by_code["E-02"].failures == 0
        assert by_code["E-02"].hours is None

    def test_a_decommissioned_asset_is_not_part_of_the_fleet(self):
        result = queries.mtbf(self.company.pk, scenario.WINDOW)

        assert "E-03" not in {row.code for row in result.by_asset}


class DecommissionedAssetTests(TestCase):
    """The seam between "the fleet" and "the work", pinned on purpose.

    A machine that was scrapped is not part of the fleet: it cannot be
    available or unavailable, so it is out of disponibilidad and MTBF. The
    repair somebody did on it three weeks ago, on the other hand, happened and
    cost money — MTTR and the cost table count it. Two different questions,
    two different populations, both written down in docs/kpis.md.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        scrapped = AssetFactory(
            company=cls.company, code="Z-99", status=Asset.Status.DADO_DE_BAJA
        )
        WorkOrderFactory(
            asset=scrapped,
            company=cls.company,
            type=WorkOrder.Type.CORRECTIVO,
            status=WorkOrder.Status.TERMINADA,
            started_at=scenario.at(9, 8),
            finished_at=scenario.at(9, 11),
            downtime_minutes=180,
            labor_cost_cop=20_000,
        )

    def test_its_repair_still_counts_as_work_done(self):
        assert queries.mttr(self.company.pk, scenario.WINDOW).repairs == 1
        assert queries.cost_by_asset_month(self.company.pk, scenario.WINDOW).total_cop == 20_000

    def test_but_it_is_no_longer_part_of_the_fleet(self):
        assert queries.mtbf(self.company.pk, scenario.WINDOW).failures == 0
        assert queries.availability(self.company.pk, scenario.WINDOW).percent is None


class MttrTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        scenario.build(cls.company)

    def test_mttr_is_the_average_repair_duration(self):
        """(2 h + 4 h) ÷ 2 reparaciones = 3,00 h. The cancelled 16-hour order
        and the one finished in February are not in it."""
        result = queries.mttr(self.company.pk, scenario.WINDOW)

        assert result.hours == scenario.EXPECTED_MTTR
        assert result.repairs == scenario.EXPECTED_MTTR_REPAIRS


class PmComplianceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        scenario.build(cls.company)

    def test_compliance_counts_what_was_scheduled_in_the_window(self):
        """3 a tiempo ÷ 5 programadas = 60,00 %. The preventive that was never
        done weighs against the plant; the cancelled one does not."""
        result = queries.pm_compliance(self.company.pk, scenario.WINDOW)

        assert result.percent == scenario.EXPECTED_COMPLIANCE
        assert result.on_time == scenario.EXPECTED_COMPLIANCE_ON_TIME
        assert result.scheduled == scenario.EXPECTED_COMPLIANCE_SCHEDULED

    def test_an_order_closed_late_at_night_still_counts_as_on_time(self):
        """23:30 in Bogotá is 04:30 UTC the next day. Compared in UTC the plant
        would be punished for closing an order in the evening."""
        company = CompanyFactory()
        asset = AssetFactory(company=company)

        WorkOrderFactory(
            asset=asset,
            company=company,
            due_date=date(2026, 5, 20),
            status=WorkOrder.Status.TERMINADA,
            finished_at=timezone.make_aware(datetime(2026, 5, 20, 23, 30)),
        )
        window = Period(
            key="mes",
            label="Mayo",
            starts_at=timezone.make_aware(datetime(2026, 5, 1)),
            ends_at=timezone.make_aware(datetime(2026, 5, 31)),
        )

        result = queries.pm_compliance(company.pk, window)

        assert (result.scheduled, result.on_time) == (1, 1)


class AvailabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        scenario.build(cls.company)

    def test_fleet_availability(self):
        """(86 400 − 360) ÷ 86 400 = 99,58 %."""
        result = queries.availability(self.company.pk, scenario.WINDOW)

        assert result.percent == scenario.EXPECTED_AVAILABILITY_FLEET
        assert result.downtime_minutes == scenario.EXPECTED_DOWNTIME

    def test_availability_per_asset(self):
        """E-01: (43 200 − 360) ÷ 43 200 = 99,17 %. E-02 never stopped."""
        result = queries.availability(self.company.pk, scenario.WINDOW)
        by_code = {row.code: row for row in result.by_asset}

        assert by_code["E-01"].percent == scenario.EXPECTED_AVAILABILITY_E1
        assert by_code["E-01"].downtime_minutes == 360
        assert by_code["E-02"].percent == scenario.EXPECTED_AVAILABILITY_E2

    def test_downtime_longer_than_the_window_never_goes_negative(self):
        """Bad data is bad data — it is not −40 % availability on a dashboard."""
        company = CompanyFactory()
        asset = AssetFactory(company=company)

        WorkOrderFactory(
            asset=asset,
            company=company,
            type=WorkOrder.Type.CORRECTIVO,
            status=WorkOrder.Status.TERMINADA,
            started_at=scenario.WINDOW.starts_at,
            finished_at=scenario.WINDOW.starts_at + timedelta(days=1),
            downtime_minutes=100_000,
        )

        result = queries.availability(company.pk, scenario.WINDOW)

        assert result.percent == Decimal("0.00")


class BacklogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        scenario.build(cls.company)

    def test_buckets(self):
        """5 vencidas al 31/03: una de 5 días, dos de 10 y 30, dos de 31 y 45.
        30 días cae en el balde «7 a 30», el borde que un `<` mal puesto se
        come."""
        result = queries.backlog(self.company.pk, scenario.TODAY)

        assert result.total == scenario.EXPECTED_BACKLOG_TOTAL
        assert result.under_7 == scenario.EXPECTED_BACKLOG_UNDER_7
        assert result.from_7_to_30 == scenario.EXPECTED_BACKLOG_7_TO_30
        assert result.over_30 == scenario.EXPECTED_BACKLOG_OVER_30

    def test_the_buckets_add_up_to_the_total(self):
        result = queries.backlog(self.company.pk, scenario.TODAY)

        assert result.under_7 + result.from_7_to_30 + result.over_30 == result.total

    def test_rows_are_the_oldest_first_with_their_age(self):
        result = queries.backlog(self.company.pk, scenario.TODAY)

        assert [row.days_late for row in result.rows] == [45, 31, 30, 10, 5]
        assert [row.bucket for row in result.rows] == [
            "mas_30",
            "mas_30",
            "de_7_a_30",
            "de_7_a_30",
            "menos_7",
        ]

    def test_a_closed_order_is_not_backlog_even_if_it_closed_late(self):
        """B6 cerró tarde: eso lo castiga el cumplimiento, no el backlog."""
        result = queries.backlog(self.company.pk, scenario.TODAY)

        assert all(row.due_date != date(2026, 3, 2) for row in result.rows)


class CostTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        scenario.build(cls.company)

    def test_cost_by_asset_and_month_ranked(self):
        """E-01: ($60 000 + $40 000) + ($40 000 + $10 000) = $150 000 en marzo.
        E-02: $30 000. La OT cancelada de $1 999 998 no entra."""
        result = queries.cost_by_asset_month(self.company.pk, scenario.WINDOW)

        assert [(row.code, row.total_cop, row.position) for row in result.rows] == [
            ("E-01", scenario.EXPECTED_COST_E1, 1),
            ("E-02", scenario.EXPECTED_COST_E2, 2),
        ]
        assert result.rows[0].labor_cop == 100_000
        assert result.rows[0].parts_cop == 50_000
        assert result.rows[0].month == date(2026, 3, 1)

    def test_the_period_total_is_the_whole_period_not_the_top_rows(self):
        result = queries.cost_by_asset_month(self.company.pk, scenario.WINDOW, limit=1)

        assert len(result.rows) == 1
        assert result.total_cop == scenario.EXPECTED_COST_TOTAL


class SiteFilterTests(TestCase):
    """The same numbers, narrowed to one plant."""

    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        cls.north = SiteFactory(company=cls.company, name="Planta Norte")
        cls.south = SiteFactory(company=cls.company, name="Planta Sur")
        scenario.build(cls.company, site=cls.north)
        # A second plant with its own broken machine, which must not show up
        # when the operator is looking at the first one.
        southern = AssetFactory(company=cls.company, site=cls.south, code="S-01")
        WorkOrderFactory(
            asset=southern,
            company=cls.company,
            type=WorkOrder.Type.CORRECTIVO,
            status=WorkOrder.Status.TERMINADA,
            started_at=scenario.WINDOW.starts_at,
            finished_at=scenario.WINDOW.starts_at + timedelta(hours=10),
            downtime_minutes=600,
            labor_cost_cop=777_000,
        )

    def test_filtering_by_site_leaves_the_other_plants_numbers_out(self):
        result = queries.mttr(self.company.pk, scenario.WINDOW, site_id=self.north.pk)

        assert result.hours == scenario.EXPECTED_MTTR
        assert result.repairs == scenario.EXPECTED_MTTR_REPAIRS

    def test_without_a_site_filter_every_plant_counts(self):
        result = queries.mttr(self.company.pk, scenario.WINDOW)

        assert result.repairs == scenario.EXPECTED_MTTR_REPAIRS + 1

    def test_costs_are_narrowed_too(self):
        result = queries.cost_by_asset_month(
            self.company.pk, scenario.WINDOW, site_id=self.north.pk
        )

        assert result.total_cop == scenario.EXPECTED_COST_TOTAL
        assert "S-01" not in {row.code for row in result.rows}


class EmptyCompanyTests(TestCase):
    """A company that signed up this morning. Nothing here may raise, and
    nothing may invent a zero where the honest answer is "no data"."""

    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()

    def test_mtbf_is_undefined(self):
        result = queries.mtbf(self.company.pk, scenario.WINDOW)

        assert result.hours is None
        assert result.failures == 0
        assert result.by_asset == []

    def test_mttr_is_undefined(self):
        assert queries.mttr(self.company.pk, scenario.WINDOW).hours is None

    def test_compliance_has_no_denominator(self):
        result = queries.pm_compliance(self.company.pk, scenario.WINDOW)

        assert result.percent is None
        assert result.scheduled == 0

    def test_availability_is_undefined_without_assets(self):
        assert queries.availability(self.company.pk, scenario.WINDOW).percent is None

    def test_backlog_is_zero(self):
        result = queries.backlog(self.company.pk, scenario.TODAY)

        assert (result.total, result.under_7, result.from_7_to_30, result.over_30) == (0, 0, 0, 0)
        assert result.rows == []

    def test_cost_is_zero_pesos_not_none(self):
        """Nobody spent anything, which is a number: $0."""
        result = queries.cost_by_asset_month(self.company.pk, scenario.WINDOW)

        assert result.total_cop == 0
        assert result.rows == []


class AssetsWithoutHistoryTests(TestCase):
    """Machines exist, but no work order has ever been written."""

    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        AssetFactory(company=cls.company, code="N-01")

    def test_a_machine_nobody_touched_is_100_percent_available(self):
        result = queries.availability(self.company.pk, scenario.WINDOW)

        assert result.percent == Decimal("100.00")

    def test_and_has_no_mtbf(self):
        result = queries.mtbf(self.company.pk, scenario.WINDOW)

        assert result.hours is None
        assert result.by_asset[0].uptime_hours == Decimal("720.00")
