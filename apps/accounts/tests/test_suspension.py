from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Subscription
from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory


class SuspensionMiddlewareTests(TestCase):
    """Acceptance criterion 4: a suspended company's user is blocked on any
    page except logout; active/trial companies pass.
    """

    def _login_with_status(self, status):
        company = CompanyFactory(subscription__status=status)
        user = AdminUserFactory(company=company)
        self.client.force_login(user)
        return user

    def test_suspended_company_blocked_on_home_and_other_pages(self):
        self._login_with_status(Subscription.Status.SUSPENDED)

        home_response = self.client.get(reverse("home"))
        sites_response = self.client.get(reverse("site_list"))

        assert home_response.status_code == 403
        assert sites_response.status_code == 403
        assert "suspendida" in home_response.content.decode().lower()

    def test_suspended_company_can_still_log_out(self):
        self._login_with_status(Subscription.Status.SUSPENDED)

        response = self.client.post(reverse("logout"))

        assert response.status_code == 302

    def test_active_company_passes(self):
        self._login_with_status(Subscription.Status.ACTIVE)

        response = self.client.get(reverse("home"))

        assert response.status_code == 200

    def test_trial_company_passes(self):
        self._login_with_status(Subscription.Status.TRIAL)

        response = self.client.get(reverse("home"))

        assert response.status_code == 200

    def test_past_due_company_is_not_suspended(self):
        self._login_with_status(Subscription.Status.PAST_DUE)

        response = self.client.get(reverse("home"))

        assert response.status_code == 200

    def test_deactivated_company_blocked_even_with_active_subscription(self):
        # Company.is_active is a separate, platform-ops kill switch from
        # Subscription.status — both must be able to block access on their own.
        company = CompanyFactory(is_active=False, subscription__status=Subscription.Status.ACTIVE)
        user = AdminUserFactory(company=company)
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        assert response.status_code == 403
