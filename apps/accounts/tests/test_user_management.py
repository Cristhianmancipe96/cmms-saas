from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory, TechnicianUserFactory

VALID_INVITE = {
    "username": "nuevo_tecnico",
    "email": "nuevo@example.com",
    "first_name": "Nuevo",
    "last_name": "Tecnico",
    "role": "technician",
    "whatsapp_phone": "",
}


class UserManagementTests(TestCase):
    """Covers Build item 5 and acceptance criterion 5 (max_users)."""

    def setUp(self):
        self.company = CompanyFactory(subscription__max_users=2)
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)

    def test_invite_creates_active_user_with_usable_temp_password(self):
        response = self.client.post(reverse("user_invite"), VALID_INVITE, follow=True)

        assert response.status_code == 200
        user = User.objects.get(username="nuevo_tecnico")
        assert user.company_id == self.company.id
        assert user.role == "technician"
        assert user.is_active is True
        assert user.has_usable_password()
        assert "Contraseña temporal" in response.content.decode()

    def test_max_users_blocks_invite_past_the_limit(self):
        # self.admin already occupies one seat; adding a second hits max_users=2.
        TechnicianUserFactory(company=self.company)

        response = self.client.post(
            reverse("user_invite"),
            {**VALID_INVITE, "username": "un_usuario_mas"},
            follow=True,
        )

        assert response.status_code == 200
        assert not User.objects.filter(username="un_usuario_mas").exists()
        assert "máximo de 2 usuarios" in response.content.decode()

    def test_admin_cannot_reach_other_company_user_by_id(self):
        other_company = CompanyFactory()
        other_user = TechnicianUserFactory(company=other_company)

        response = self.client.get(reverse("user_deactivate", args=[other_user.pk]))

        assert response.status_code == 404

    def test_deactivate_disables_login(self):
        target = TechnicianUserFactory(company=self.company)

        response = self.client.post(reverse("user_deactivate", args=[target.pk]), follow=True)

        target.refresh_from_db()
        assert response.status_code == 200
        assert target.is_active is False

    def test_invite_without_role_is_rejected(self):
        """Brief 01 review finding: role is blank=True on the model (platform
        admins carry role=""), but an invited company user must always get a
        real role — otherwise role_required silently locks them out of every
        screen with no way to self-fix.
        """
        response = self.client.post(
            reverse("user_invite"),
            {**VALID_INVITE, "username": "sin_rol", "role": ""},
            follow=True,
        )

        assert response.status_code == 200
        assert not User.objects.filter(username="sin_rol").exists()
        assert "Rol" in response.content.decode()
