from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory, SiteFactory


class TenantIsolationTests(TestCase):
    """Acceptance criteria 1 and 2 of brief 01: cross-tenant URL manipulation
    404s, and the default manager never leaks other-company rows even from
    the naive `Site.objects.all()` used by the real SiteListView.
    """

    def setUp(self):
        self.company_a = CompanyFactory()
        self.company_b = CompanyFactory()
        self.site_a = SiteFactory(company=self.company_a, name="Planta A")
        self.site_b = SiteFactory(company=self.company_b, name="Planta B")
        self.admin_a = AdminUserFactory(company=self.company_a)
        self.client.force_login(self.admin_a)

    def test_detail_url_of_other_company_site_is_404_not_403(self):
        response = self.client.get(reverse("site_detail", args=[self.site_b.pk]))

        assert response.status_code == 404

    def test_edit_url_of_other_company_site_is_404_not_403(self):
        response = self.client.get(reverse("site_update", args=[self.site_b.pk]))

        assert response.status_code == 404

    def test_own_company_site_is_reachable(self):
        response = self.client.get(reverse("site_detail", args=[self.site_a.pk]))

        assert response.status_code == 200

    def test_list_view_naive_manager_never_returns_other_company_rows(self):
        response = self.client.get(reverse("site_list"))
        content = response.content.decode()

        assert self.site_a.name in content
        assert self.site_b.name not in content
