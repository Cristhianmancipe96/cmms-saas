from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory
from apps.assets.tests.factories import AssetDocumentFactory, AssetFactory


class AssetTenantIsolationTests(TestCase):
    """Acceptance criteria 1 and 2: a company-B user gets 404 (never 403, never
    the actual bytes) on company-A's asset detail, edit and document URLs.
    """

    def setUp(self):
        self.company_a = CompanyFactory()
        self.company_b = CompanyFactory()
        self.asset_a = AssetFactory(company=self.company_a, name="Empacadora A")
        self.asset_b = AssetFactory(company=self.company_b, name="Empacadora B")
        self.document_b = AssetDocumentFactory(asset=self.asset_b)
        self.admin_a = AdminUserFactory(company=self.company_a)
        self.client.force_login(self.admin_a)

    def test_detail_of_other_company_asset_is_404(self):
        response = self.client.get(reverse("asset_detail", args=[self.asset_b.pk]))

        assert response.status_code == 404

    def test_edit_of_other_company_asset_is_404(self):
        response = self.client.get(reverse("asset_update", args=[self.asset_b.pk]))

        assert response.status_code == 404

    def test_document_url_of_other_company_asset_is_404_no_bytes_served(self):
        response = self.client.get(reverse("assetdocument_download", args=[self.document_b.pk]))

        assert response.status_code == 404
        assert b"%PDF-1.4 test" not in response.content

    def test_photo_url_of_other_company_asset_is_404(self):
        response = self.client.get(reverse("asset_photo_download", args=[self.asset_b.pk]))

        assert response.status_code == 404

    def test_own_company_asset_is_reachable(self):
        response = self.client.get(reverse("asset_detail", args=[self.asset_a.pk]))

        assert response.status_code == 200

    def test_list_view_never_returns_other_company_rows(self):
        response = self.client.get(reverse("asset_list"))
        content = response.content.decode()

        assert self.asset_a.name in content
        assert self.asset_b.name not in content


class AssetAnonymousAccessTests(TestCase):
    """Acceptance criterion 3: anonymous requests redirect to login — no
    bytes served, no 403 leaking that the object even exists.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.document = AssetDocumentFactory(asset=self.asset)

    def test_anonymous_detail_redirects_to_login(self):
        response = self.client.get(reverse("asset_detail", args=[self.asset.pk]))

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))

    def test_anonymous_document_download_redirects_to_login(self):
        response = self.client.get(reverse("assetdocument_download", args=[self.document.pk]))

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))

    def test_anonymous_photo_download_redirects_to_login(self):
        response = self.client.get(reverse("asset_photo_download", args=[self.asset.pk]))

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))
