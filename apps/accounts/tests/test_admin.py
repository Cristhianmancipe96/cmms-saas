from django.test import TestCase

from apps.accounts.tests.factories import (
    CompanyFactory,
    PlatformAdminUserFactory,
    SiteFactory,
    UserFactory,
)

SITE_ADMIN_URL = "/admin/accounts/site/"
USER_ADMIN_URL = "/admin/accounts/user/"


def _staffer_without_platform_admin(company):
    """An is_staff (+ is_superuser, so Django's own permission checks never
    get in the way) account that is deliberately NOT is_platform_admin — the
    exact shape the confirmed admin-scoping findings describe.
    """
    return UserFactory(
        company=company,
        role="admin",
        is_staff=True,
        is_superuser=True,
        is_platform_admin=False,
    )


class SiteAdminScopingTests(TestCase):
    """`.unscoped()` in SiteAdmin must stay reserved for is_platform_admin —
    the whole point of apps/core/tenancy.py's contract.
    """

    def test_platform_admin_sees_every_company_site(self):
        SiteFactory(name="Planta A", company=CompanyFactory())
        SiteFactory(name="Planta B", company=CompanyFactory())
        platform_admin = PlatformAdminUserFactory()
        self.client.force_login(platform_admin)

        response = self.client.get(SITE_ADMIN_URL)
        content = response.content.decode()

        assert "Planta A" in content
        assert "Planta B" in content

    def test_staff_without_platform_admin_flag_sees_only_own_company(self):
        # is_staff decides who reaches /admin/ at all (brief 10's job); this
        # test only proves the queryset itself never leaks once someone is
        # already in, regardless of how they got is_staff.
        own_company = CompanyFactory()
        other_company = CompanyFactory()
        SiteFactory(name="Planta Propia", company=own_company)
        SiteFactory(name="Planta Ajena", company=other_company)
        self.client.force_login(_staffer_without_platform_admin(own_company))

        response = self.client.get(SITE_ADMIN_URL)
        content = response.content.decode()

        assert "Planta Propia" in content
        assert "Planta Ajena" not in content


class CompanyUserAdminScopingTests(TestCase):
    def test_platform_admin_sees_every_company_user(self):
        company_a = CompanyFactory()
        company_b = CompanyFactory()
        UserFactory(username="user_de_a", company=company_a)
        UserFactory(username="user_de_b", company=company_b)
        platform_admin = PlatformAdminUserFactory()
        self.client.force_login(platform_admin)

        response = self.client.get(USER_ADMIN_URL)
        content = response.content.decode()

        assert "user_de_a" in content
        assert "user_de_b" in content

    def test_staff_without_platform_admin_flag_sees_only_own_company_users(self):
        own_company = CompanyFactory()
        other_company = CompanyFactory()
        UserFactory(username="propio", company=own_company)
        UserFactory(username="ajeno", company=other_company)
        self.client.force_login(_staffer_without_platform_admin(own_company))

        response = self.client.get(USER_ADMIN_URL)
        content = response.content.decode()

        assert "propio" in content
        assert "ajeno" not in content
