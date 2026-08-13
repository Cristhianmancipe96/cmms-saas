from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    PlatformAdminUserFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)


class AuthTests(TestCase):
    """Acceptance criterion 7: login/logout work; role routing test."""

    def setUp(self):
        self.company = CompanyFactory()

    def test_login_failure_shows_spanish_error(self):
        AdminUserFactory(company=self.company, username="ana")

        response = self.client.post(reverse("login"), {"username": "ana", "password": "wrong"})

        assert response.status_code == 200
        assert "incorrectos" in response.content.decode()

    def test_logout_requires_post_and_redirects_to_login(self):
        user = AdminUserFactory(company=self.company)
        self.client.force_login(user)

        response = self.client.post(reverse("logout"))

        assert response.status_code == 302
        assert response.url == reverse("login")

    def test_password_change_requires_login(self):
        response = self.client.get(reverse("password_change"))

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))

    def test_every_role_routes_to_home_after_login(self):
        factories = (
            AdminUserFactory,
            SupervisorUserFactory,
            TechnicianUserFactory,
            StaffUserFactory,
        )
        for factory_cls in factories:
            with self.subTest(factory=factory_cls.__name__):
                user = factory_cls(company=CompanyFactory(), username=f"u_{factory_cls.__name__}")
                user.set_password("testpass123")
                user.save()

                response = self.client.post(
                    reverse("login"),
                    {"username": user.username, "password": "testpass123"},
                )

                assert response.status_code == 302
                assert response.url == reverse("home")
                self.client.logout()

    def test_platform_admin_also_routes_to_home(self):
        user = PlatformAdminUserFactory(username="root_admin")
        user.set_password("testpass123")
        user.save()

        response = self.client.post(
            reverse("login"), {"username": "root_admin", "password": "testpass123"}
        )

        assert response.status_code == 302
        assert response.url == reverse("home")
