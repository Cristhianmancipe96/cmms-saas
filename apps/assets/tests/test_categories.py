from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory, TechnicianUserFactory
from apps.assets.models import AssetCategory


class AssetCategoryTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()

    def test_admin_can_create_category(self):
        admin = AdminUserFactory(company=self.company)
        self.client.force_login(admin)

        response = self.client.post(
            reverse("assetcategory_create"), {"name": "Compresores"}, follow=True
        )

        assert response.status_code == 200
        # .unscoped(): the tenant contextvar is already reset once the
        # client request has finished (apps/core/tenancy.py).
        assert AssetCategory.objects.unscoped().filter(
            company=self.company, name="Compresores"
        ).exists()

    def test_technician_cannot_create_category(self):
        technician = TechnicianUserFactory(company=self.company)
        self.client.force_login(technician)

        response = self.client.get(reverse("assetcategory_create"))

        assert response.status_code == 403

    def test_technician_can_list_categories(self):
        technician = TechnicianUserFactory(company=self.company)
        self.client.force_login(technician)

        response = self.client.get(reverse("assetcategory_list"))

        assert response.status_code == 200
