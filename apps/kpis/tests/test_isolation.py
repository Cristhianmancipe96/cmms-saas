"""The test this module exists for.

Raw SQL has no scoped manager behind it: if `company_id = %s` is missing from
one predicate, the dashboard quietly reports another plant's downtime as
yours. So the check is not "does the query filter by company" — it is: build
the *identical* scenario twice, once for company A and once for company B,
and assert that every single indicator for A is byte-for-byte what it was when
A was alone in the database.
"""

from django.test import TestCase

from apps.accounts.tests.factories import CompanyFactory
from apps.kpis import queries
from apps.kpis.tests import scenario


class NoiseFromAnotherCompanyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = CompanyFactory(name="Empresa A")
        cls.company_b = CompanyFactory(name="Empresa B")
        cls.company_c = CompanyFactory(name="Empresa C")
        scenario.build(cls.company_a)
        # The same plant three times over — same asset codes, same failures,
        # same pesos. A leaking predicate does not shift A's numbers slightly,
        # it triples them, so every assertion below is a tripwire.
        scenario.build(cls.company_b)
        scenario.build(cls.company_c)

    def test_mtbf(self):
        result = queries.mtbf(self.company_a.pk, scenario.WINDOW)

        assert result.hours == scenario.EXPECTED_MTBF_FLEET
        assert result.failures == scenario.EXPECTED_FAILURES
        assert {row.code for row in result.by_asset} == {"E-01", "E-02"}

    def test_mttr(self):
        result = queries.mttr(self.company_a.pk, scenario.WINDOW)

        assert result.hours == scenario.EXPECTED_MTTR
        assert result.repairs == scenario.EXPECTED_MTTR_REPAIRS

    def test_pm_compliance(self):
        result = queries.pm_compliance(self.company_a.pk, scenario.WINDOW)

        assert result.percent == scenario.EXPECTED_COMPLIANCE
        assert result.scheduled == scenario.EXPECTED_COMPLIANCE_SCHEDULED

    def test_availability(self):
        result = queries.availability(self.company_a.pk, scenario.WINDOW)

        assert result.percent == scenario.EXPECTED_AVAILABILITY_FLEET
        assert result.downtime_minutes == scenario.EXPECTED_DOWNTIME

    def test_backlog(self):
        result = queries.backlog(self.company_a.pk, scenario.TODAY)

        assert result.total == scenario.EXPECTED_BACKLOG_TOTAL
        assert len(result.rows) == scenario.EXPECTED_BACKLOG_TOTAL

    def test_cost(self):
        result = queries.cost_by_asset_month(self.company_a.pk, scenario.WINDOW)

        assert result.total_cop == scenario.EXPECTED_COST_TOTAL
        assert len(result.rows) == 2

    def test_the_other_companies_see_their_own_identical_numbers(self):
        """The mirror image of the assertions above, and the reason they mean
        something: B and C really do have their own rows in the same tables,
        so the tests are not passing because the noise failed to be created."""
        for company in (self.company_b, self.company_c):
            result = queries.cost_by_asset_month(company.pk, scenario.WINDOW)

            assert result.total_cop == scenario.EXPECTED_COST_TOTAL
