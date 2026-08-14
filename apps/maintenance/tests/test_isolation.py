"""Acceptance criterion 7, URL half: company B never reaches company A's
plans, and never writes a reading on A's equipment.

404 rather than 403 throughout: a 403 would confirm the object exists.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory
from apps.assets.tests.factories import AssetFactory
from apps.maintenance.models import MeterReading
from apps.maintenance.tests.factories import MaintenancePlanFactory


class PlanTenantIsolationTests(TestCase):
    def setUp(self):
        self.company_a = CompanyFactory()
        self.company_b = CompanyFactory()
        self.asset_a = AssetFactory(company=self.company_a)
        self.asset_b = AssetFactory(company=self.company_b)
        self.plan_a = MaintenancePlanFactory(
            company=self.company_a, asset=self.asset_a, name="Plan de A"
        )
        self.plan_b = MaintenancePlanFactory(
            company=self.company_b, asset=self.asset_b, name="Plan de B"
        )
        self.client.force_login(AdminUserFactory(company=self.company_a))

    def test_detail_of_another_companys_plan_is_404(self):
        response = self.client.get(reverse("maintenanceplan_detail", args=[self.plan_b.pk]))

        assert response.status_code == 404

    def test_update_of_another_companys_plan_is_404(self):
        response = self.client.get(reverse("maintenanceplan_update", args=[self.plan_b.pk]))

        assert response.status_code == 404

    def test_toggling_another_companys_plan_is_404(self):
        response = self.client.post(reverse("maintenanceplan_toggle", args=[self.plan_b.pk]))

        assert response.status_code == 404
        self.plan_b.refresh_from_db()
        assert self.plan_b.is_active is True

    def test_deleting_another_companys_plan_is_404(self):
        response = self.client.post(reverse("maintenanceplan_delete", args=[self.plan_b.pk]))

        assert response.status_code == 404

    def test_creating_a_plan_on_another_companys_asset_is_404(self):
        response = self.client.get(
            reverse("maintenanceplan_create", args=[self.asset_b.pk])
        )

        assert response.status_code == 404

    def test_recording_a_reading_on_another_companys_asset_is_404(self):
        response = self.client.post(
            reverse("meterreading_create", args=[self.asset_b.pk]), {"reading_hours": "10"}
        )

        assert response.status_code == 404
        assert MeterReading.objects.unscoped().filter(asset=self.asset_b).count() == 0

    def test_the_list_never_shows_another_companys_plans(self):
        content = self.client.get(reverse("maintenanceplan_list")).content.decode()

        assert "Plan de A" in content
        assert "Plan de B" not in content

    def test_own_plan_stays_reachable(self):
        response = self.client.get(reverse("maintenanceplan_detail", args=[self.plan_a.pk]))

        assert response.status_code == 200


class PlanAnonymousAccessTests(TestCase):
    """No bytes for anonymous requests — a redirect to login, never a 403
    that would confirm the object exists."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.plan = MaintenancePlanFactory(company=self.company, asset=self.asset)

    def test_anonymous_list_redirects_to_login(self):
        response = self.client.get(reverse("maintenanceplan_list"))

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))

    def test_anonymous_detail_redirects_to_login(self):
        response = self.client.get(reverse("maintenanceplan_detail", args=[self.plan.pk]))

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))

    def test_anonymous_reading_post_redirects_to_login(self):
        response = self.client.post(
            reverse("meterreading_create", args=[self.asset.pk]),
            {"reading_hours": Decimal("5")},
        )

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))
        assert MeterReading.objects.unscoped().count() == 0
