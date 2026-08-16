"""The dashboard screen: who opens it, what it recalculates, what it costs.

The arithmetic is already pinned down in `test_queries.py` against a
hand-computed scenario; these tests are about the page — the roles, the
switcher, the tenant boundary as a *user* crosses it, and the Spanish empty
states a demo company has to render without a single error.
"""

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    PlatformAdminUserFactory,
    SiteFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.workorders.models import WorkOrder
from apps.workorders.tests.factories import WorkOrderFactory

URL = reverse("kpi_dashboard")


def repair(asset, *, days_ago: int, hours: int = 2, downtime: int = 60, cost: int = 10_000):
    """A corrective work order finished `days_ago` days ago, in `hours` hours.

    Relative to now on purpose: unlike the SQL tests, these exercise the
    period switcher, whose windows are measured from the current clock.
    """
    finished_at = timezone.now() - timedelta(days=days_ago)
    return WorkOrderFactory(
        asset=asset,
        company=asset.company,
        type=WorkOrder.Type.CORRECTIVO,
        origin=WorkOrder.Origin.MANUAL,
        status=WorkOrder.Status.TERMINADA,
        started_at=finished_at - timedelta(hours=hours),
        finished_at=finished_at,
        downtime_minutes=downtime,
        labor_cost_cop=cost,
    )


class AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()

    def test_an_admin_opens_it(self):
        self.client.force_login(AdminUserFactory(company=self.company))

        assert self.client.get(URL).status_code == 200

    def test_a_supervisor_opens_it(self):
        self.client.force_login(SupervisorUserFactory(company=self.company))

        assert self.client.get(URL).status_code == 200

    def test_staff_reads_it(self):
        """The office asks «¿cuánto nos costó la empacadora?» too. The screen
        is read-only for everyone, so there is nothing to withhold."""
        self.client.force_login(StaffUserFactory(company=self.company))

        assert self.client.get(URL).status_code == 200

    def test_a_technician_does_not(self):
        """Not a privilege call: a technician's screen is «Mis OTs». Fleet
        MTBF on a plant-floor phone is noise between them and the job."""
        self.client.force_login(TechnicianUserFactory(company=self.company))

        assert self.client.get(URL).status_code == 403

    def test_an_anonymous_visitor_is_sent_to_the_login_page(self):
        response = self.client.get(URL)

        assert response.status_code == 302
        assert reverse("login") in response.url

    def test_a_platform_admin_has_no_company_to_report_on(self):
        """Cross-tenant analytics is out of scope: there is no `company_id` to
        bind, and inventing one would be the leak this module fears most. The
        nav does not offer them a link to their own 403 either."""
        self.client.force_login(PlatformAdminUserFactory())

        response = self.client.get(URL)

        assert response.status_code == 403
        assert URL not in self.client.get(reverse("workorder_list")).content.decode()

    def test_the_nav_offers_it_to_everyone_but_technicians(self):
        self.client.force_login(TechnicianUserFactory(company=self.company))
        technician_page = self.client.get(reverse("workorder_mine")).content.decode()

        self.client.force_login(SupervisorUserFactory(company=self.company))
        supervisor_page = self.client.get(URL).content.decode()

        assert URL not in technician_page
        assert URL in supervisor_page


class PeriodSwitcherTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        cls.asset = AssetFactory(company=cls.company, code="E-01")
        repair(cls.asset, days_ago=3)
        repair(cls.asset, days_ago=45)

    def setUp(self):
        self.client.force_login(AdminUserFactory(company=self.company))

    def test_the_default_period_is_the_last_30_days(self):
        response = self.client.get(URL)

        assert response.context["period"].key == "30d"
        assert response.context["mttr"].repairs == 1

    def test_a_wider_period_takes_in_the_older_failure(self):
        response = self.client.get(URL, {"periodo": "90d"})

        assert response.context["period"].key == "90d"
        assert response.context["mttr"].repairs == 2
        assert response.context["mtbf"].failures == 2

    def test_an_unknown_period_falls_back_to_the_default(self):
        """A mistyped URL is not a 500 on the screen an admin opens daily."""
        response = self.client.get(URL, {"periodo": "'; DROP TABLE"})

        assert response.status_code == 200
        assert response.context["period"].key == "30d"

    def test_htmx_gets_only_the_numbers_back(self):
        response = self.client.get(URL, {"periodo": "90d"}, headers={"hx-request": "true"})
        body = response.content.decode()

        assert response.status_code == 200
        assert "<html" not in body
        assert "Costo por equipo y mes" in body


class SiteFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        cls.north = SiteFactory(company=cls.company, name="Planta Norte")
        cls.south = SiteFactory(company=cls.company, name="Planta Sur")
        repair(AssetFactory(company=cls.company, site=cls.north, code="N-01"), days_ago=2)
        repair(AssetFactory(company=cls.company, site=cls.south, code="S-01"), days_ago=2)

    def setUp(self):
        self.client.force_login(AdminUserFactory(company=self.company))

    def test_filtering_narrows_the_numbers_to_one_plant(self):
        response = self.client.get(URL, {"sede": self.north.pk})

        assert response.context["mttr"].repairs == 1
        assert response.context["selected_site"] == self.north

    def test_another_companys_site_id_is_not_a_filter(self):
        """It resolves to None — «todas las sedes» — instead of narrowing this
        company's numbers by a row it does not own."""
        foreign_site = SiteFactory(company=CompanyFactory())

        response = self.client.get(URL, {"sede": foreign_site.pk})

        assert response.context["selected_site"] is None
        assert response.context["mttr"].repairs == 2

    def test_a_nonsense_site_is_ignored(self):
        response = self.client.get(URL, {"sede": "../etc/passwd"})

        assert response.status_code == 200
        assert response.context["selected_site"] is None


class IsolationTests(TestCase):
    def test_an_admin_of_company_b_never_sees_company_a_numbers(self):
        company_a = CompanyFactory(name="Empresa A")
        company_b = CompanyFactory(name="Empresa B")
        repair(AssetFactory(company=company_a, code="A-01"), days_ago=2, cost=900_000)
        repair(AssetFactory(company=company_b, code="B-01"), days_ago=2, cost=15_000)
        self.client.force_login(AdminUserFactory(company=company_b))

        response = self.client.get(URL)
        body = response.content.decode()

        assert response.context["cost"].total_cop == 15_000
        assert response.context["mttr"].repairs == 1
        assert "A-01" not in body
        assert "B-01" in body


class EmptyCompanyTests(TestCase):
    """The demo company on its first day: no assets, no work orders, no data.
    Nothing on this page may raise, and every missing number says «—»."""

    def setUp(self):
        self.company = CompanyFactory()
        self.client.force_login(AdminUserFactory(company=self.company))

    def test_it_renders_with_spanish_empty_states(self):
        response = self.client.get(URL)
        body = response.content.decode()

        assert response.status_code == 200
        assert "—" in body
        assert "Sin OTs vencidas." in body
        assert "Sin costos registrados en el período." in body

    def test_no_indicator_divides_by_zero(self):
        response = self.client.get(URL)

        assert response.context["mtbf"].hours is None
        assert response.context["mttr"].hours is None
        assert response.context["compliance"].percent is None
        assert response.context["availability"].percent is None
        assert response.context["backlog"].total == 0
        assert response.context["cost"].total_cop == 0


class QueryBudgetTests(TestCase):
    """Six indicators, eight statements, and no list on the page that grows a
    query per row: the dashboard must stay a fixed-cost page as the plant's
    history grows, or the admin stops opening it."""

    def test_the_page_costs_the_same_with_one_asset_as_with_twenty(self):
        company = CompanyFactory()
        site = SiteFactory(company=company)
        repair(AssetFactory(company=company, site=site), days_ago=2)
        self.client.force_login(AdminUserFactory(company=company))
        with CaptureQueriesContext(connection) as small:
            self.client.get(URL)

        for index in range(20):
            asset = AssetFactory(company=company, site=site, code=f"X-{index:02d}")
            repair(asset, days_ago=index % 25 + 1)
        with CaptureQueriesContext(connection) as large:
            self.client.get(URL)

        assert len(large) == len(small)
        assert len(large) <= 15
