from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import PlatformAdminUserFactory, SiteFactory


class PlatformAdminAccessTests(TestCase):
    """Acceptance criterion 6: platform admin reaches cross-company data
    only through an explicit `objects.unscoped()` code path — never the
    default manager, even though `role_required` lets them through.
    """

    def test_platform_admin_sees_nothing_through_the_default_scoped_view(self):
        SiteFactory(name="Planta Oculta")
        platform_admin = PlatformAdminUserFactory()
        self.client.force_login(platform_admin)

        response = self.client.get(reverse("site_list"))

        assert response.status_code == 200
        assert "Planta Oculta" not in response.content.decode()

    def test_platform_admin_gets_403_not_a_crash_on_site_create(self):
        # is_platform_admin bypasses the role gate but has no company of its
        # own; the view has no "create for which company" selector.
        platform_admin = PlatformAdminUserFactory()
        self.client.force_login(platform_admin)

        response = self.client.post(reverse("site_create"), {"name": "Planta X", "address": ""})

        assert response.status_code == 403

    def test_platform_admin_gets_403_not_a_crash_on_user_invite(self):
        platform_admin = PlatformAdminUserFactory()
        self.client.force_login(platform_admin)

        response = self.client.get(reverse("user_invite"))

        assert response.status_code == 403
