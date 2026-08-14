from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory

MANAGER_FACTORIES = (AdminUserFactory, SupervisorUserFactory)
READONLY_FACTORIES = (TechnicianUserFactory, StaffUserFactory)


class AssetRoleMatrixTests(TestCase):
    """Acceptance criterion 4: admin/supervisor can create+edit; technician
    and staff are read-only (200 on list/detail, 403 on create/edit).
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)

    def _login_as(self, factory_cls):
        user = factory_cls(company=self.company)
        self.client.force_login(user)
        return user

    def test_create_allows_admin_and_supervisor(self):
        for factory_cls in MANAGER_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("asset_create"))
                assert response.status_code == 200
                self.client.logout()

    def test_create_blocks_technician_and_staff(self):
        for factory_cls in READONLY_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("asset_create"))
                assert response.status_code == 403
                assert "No tienes permiso" in response.content.decode()
                self.client.logout()

    def test_edit_allows_admin_and_supervisor(self):
        for factory_cls in MANAGER_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("asset_update", args=[self.asset.pk]))
                assert response.status_code == 200
                self.client.logout()

    def test_edit_blocks_technician_and_staff(self):
        for factory_cls in READONLY_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("asset_update", args=[self.asset.pk]))
                assert response.status_code == 403
                self.client.logout()

    def test_all_roles_can_read_list_and_detail(self):
        for factory_cls in (*MANAGER_FACTORIES, *READONLY_FACTORIES):
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                list_response = self.client.get(reverse("asset_list"))
                detail_response = self.client.get(reverse("asset_detail", args=[self.asset.pk]))
                assert list_response.status_code == 200
                assert detail_response.status_code == 200
                self.client.logout()

    def test_baja_and_delete_block_technician_and_staff(self):
        for factory_cls in READONLY_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                baja_response = self.client.get(reverse("asset_baja", args=[self.asset.pk]))
                delete_response = self.client.get(reverse("asset_delete", args=[self.asset.pk]))
                assert baja_response.status_code == 403
                assert delete_response.status_code == 403
                self.client.logout()
