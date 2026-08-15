"""The printable label: who may print one, and what the code actually says.

A QR is unreadable to a reviewer, so the encoding is verified the only way
that proves anything without a decoder: re-encode the URL the label is
supposed to carry, with the same parameters, and require the page's SVG to be
that exact drawing. A label pointing anywhere else cannot pass.
"""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets import qr
from apps.assets.tests.factories import AssetFactory

SITE_URL = "https://vectron.example.com"


class LabelContentTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory(name="Alimentos del Valle")
        self.asset = AssetFactory(
            company=self.company, code="FLOW-07", name="Empacadora Flowpac 7"
        )
        self.url = reverse("asset_label", args=[self.asset.pk])
        self.client.force_login(SupervisorUserFactory(company=self.company))

    def test_scan_url_is_absolute_and_built_from_site_url(self):
        with self.settings(SITE_URL=SITE_URL):
            assert qr.asset_scan_url(self.asset) == f"{SITE_URL}/e/{self.asset.qr_uuid}"

    def test_trailing_slash_in_site_url_does_not_double_up(self):
        with self.settings(SITE_URL=f"{SITE_URL}/"):
            assert qr.asset_scan_url(self.asset) == f"{SITE_URL}/e/{self.asset.qr_uuid}"

    def test_printed_qr_encodes_that_absolute_url(self):
        with self.settings(SITE_URL=SITE_URL):
            content = self.client.get(self.url).content.decode()

            expected = qr.qr_svg(f"{SITE_URL}/e/{self.asset.qr_uuid}")
            assert str(expected) in content

    def test_printed_qr_does_not_encode_the_primary_key(self):
        with self.settings(SITE_URL=SITE_URL):
            content = self.client.get(self.url).content.decode()

            assert str(qr.qr_svg(f"{SITE_URL}/e/{self.asset.pk}")) not in content

    def test_shows_code_name_company_and_the_typed_fallback(self):
        with self.settings(SITE_URL=SITE_URL):
            content = self.client.get(self.url).content.decode()

        assert "FLOW-07" in content
        assert "Empacadora Flowpac 7" in content
        assert "Alimentos del Valle" in content
        assert f"{SITE_URL}/e/{self.asset.qr_uuid}" in content

    def test_a_localhost_site_url_stops_the_print_with_a_warning(self):
        """The label's own silent no-op: a page that looks perfect and a
        sticker that resolves on nobody's phone but the developer's."""
        with self.settings(SITE_URL="http://localhost:8000"):
            content = self.client.get(self.url).content.decode()

        assert "No imprimas todavía." in content
        assert qr.is_local_url("http://127.0.0.1:8000/e/x")
        assert qr.is_local_url("http://localhost:8000/e/x")

    def test_a_real_site_url_prints_without_a_warning(self):
        with self.settings(SITE_URL=SITE_URL):
            content = self.client.get(self.url).content.decode()

        assert "No imprimas todavía." not in content
        assert not qr.is_local_url(f"{SITE_URL}/e/x")

    def test_a_new_uuid_would_mean_a_new_code(self):
        """The label is bound to `qr_uuid`, not to the asset row: reprinting
        after a regenerated UUID cannot silently keep the old drawing."""
        with self.settings(SITE_URL=SITE_URL):
            before = qr.asset_scan_url(self.asset)
            other = AssetFactory(company=self.company, code="FLOW-08")

            assert qr.asset_scan_url(other) != before


class LabelPermissionTests(TestCase):
    """Whoever prints a label decides what a machine answers to for the rest
    of its life. That sits with the people who own the equipment list."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.url = reverse("asset_label", args=[self.asset.pk])

    def _status_for(self, user):
        self.client.force_login(user)
        return self.client.get(self.url).status_code

    def test_supervisor_and_admin_may_print(self):
        assert self._status_for(SupervisorUserFactory(company=self.company)) == 200
        assert self._status_for(AdminUserFactory(company=self.company)) == 200

    def test_technician_may_not(self):
        assert self._status_for(TechnicianUserFactory(company=self.company)) == 403

    def test_staff_may_not(self):
        assert self._status_for(StaffUserFactory(company=self.company)) == 403

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.url)

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))

    def test_another_companys_label_is_a_404_not_a_403(self):
        other_admin = AdminUserFactory(company=CompanyFactory())

        assert self._status_for(other_admin) == 404

    def test_the_detail_screen_offers_the_button_only_to_managers(self):
        detail = reverse("asset_detail", args=[self.asset.pk])

        self.client.force_login(SupervisorUserFactory(company=self.company))
        assert self.url in self.client.get(detail).content.decode()

        self.client.force_login(TechnicianUserFactory(company=self.company))
        assert self.url not in self.client.get(detail).content.decode()
