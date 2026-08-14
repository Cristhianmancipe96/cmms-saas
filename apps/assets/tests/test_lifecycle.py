from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory
from apps.assets.models import Asset
from apps.assets.tests.factories import AssetDocumentFactory, AssetFactory


class AssetBajaTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)

    def test_baja_sets_status_and_reason(self):
        asset = AssetFactory(company=self.company, status=Asset.Status.OPERATIVO)

        response = self.client.post(
            reverse("asset_baja", args=[asset.pk]),
            {"reason": "Falla mecánica irreparable"},
            follow=True,
        )

        asset.refresh_from_db()
        assert response.status_code == 200
        assert asset.status == Asset.Status.DADO_DE_BAJA
        assert asset.baja_reason == "Falla mecánica irreparable"


class AssetDeleteTests(TestCase):
    """Acceptance criterion 7, HTTP path: an asset with a document attached
    cannot be deleted through the view either — only dado_de_baja.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)

    def test_delete_blocked_when_asset_has_documents(self):
        asset = AssetFactory(company=self.company)
        AssetDocumentFactory(asset=asset)

        response = self.client.post(reverse("asset_delete", args=[asset.pk]), follow=True)

        # .unscoped(): the tenant contextvar is already reset once the
        # client request has finished (apps/core/tenancy.py).
        assert response.status_code == 200
        assert Asset.objects.unscoped().filter(pk=asset.pk).exists()
        assert "no se puede eliminar" in response.content.decode().lower()

    def test_delete_allowed_when_asset_has_no_documents(self):
        asset = AssetFactory(company=self.company)

        response = self.client.post(reverse("asset_delete", args=[asset.pk]), follow=True)

        assert response.status_code == 200
        assert not Asset.objects.unscoped().filter(pk=asset.pk).exists()
