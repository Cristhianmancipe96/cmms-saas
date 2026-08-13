from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)


class RoleRequiredMatrixTests(TestCase):
    """Acceptance criterion 3: role_required blocks each role correctly,
    with a 403 Spanish page, gated only through the shared decorator/mixin.
    """

    def setUp(self):
        self.company = CompanyFactory()

    def _login_as(self, factory_cls):
        user = factory_cls(company=self.company)
        self.client.force_login(user)
        return user

    def test_site_create_allows_admin_and_supervisor(self):
        for factory_cls in (AdminUserFactory, SupervisorUserFactory):
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("site_create"))
                assert response.status_code == 200
                self.client.logout()

    def test_site_create_blocks_technician_and_staff(self):
        for factory_cls in (TechnicianUserFactory, StaffUserFactory):
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("site_create"))
                assert response.status_code == 403
                assert "No tienes permiso" in response.content.decode()
                self.client.logout()

    def test_user_list_allows_only_admin(self):
        matrix = (
            (AdminUserFactory, 200),
            (SupervisorUserFactory, 403),
            (TechnicianUserFactory, 403),
            (StaffUserFactory, 403),
        )
        for factory_cls, expected_status in matrix:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("user_list"))
                assert response.status_code == expected_status
                self.client.logout()

    def test_anonymous_is_redirected_to_login_not_403(self):
        response = self.client.get(reverse("site_create"))

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))
