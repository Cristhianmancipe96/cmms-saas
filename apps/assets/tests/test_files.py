import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory, SiteFactory
from apps.assets.models import Asset, AssetDocument
from apps.assets.tests.factories import AssetCategoryFactory, AssetFactory

ASSET_FORM_BASE = {
    "code": "FLOW-99",
    "name": "Empacadora nueva",
    "brand": "Flowpac",
    "model": "FP-3000",
    "serial_number": "SN-000999",
    "criticality": "media",
    "location_detail": "Línea 2",
}


def real_jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), color="red").save(buffer, format="JPEG")
    return buffer.getvalue()


def decompression_bomb_png_bytes() -> bytes:
    """A solid-color PNG that compresses to well under 1 MB on disk but
    decodes to tens of megapixels — small enough to sail past the byte-size
    cap, huge enough to blow up memory once fully decoded.
    """
    buffer = io.BytesIO()
    Image.new("RGB", (6400, 6400), color=(10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class AssetUploadValidationTests(TestCase):
    """Acceptance criterion 5: a forbidden extension or an oversized upload
    is rejected with a Spanish message — checked at the asset create view
    (main photo) and the document upload view.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.site = SiteFactory(company=self.company)
        self.category = AssetCategoryFactory(company=self.company)
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)

    def _create_payload(self, **overrides):
        payload = {**ASSET_FORM_BASE, "site": self.site.pk, "category": self.category.pk}
        payload.update(overrides)
        return payload

    def test_forbidden_extension_on_main_photo_is_rejected_in_spanish(self):
        malicious = SimpleUploadedFile(
            "shell.exe", b"MZ-not-really-an-executable", content_type="application/octet-stream"
        )
        response = self.client.post(
            reverse("asset_create"),
            self._create_payload(main_photo=malicious),
        )

        assert response.status_code == 200
        assert "Formato no permitido" in response.content.decode()

    def test_oversized_main_photo_is_rejected_in_spanish(self):
        too_big = SimpleUploadedFile(
            "foto.jpg", b"0" * (10 * 1024 * 1024 + 1), content_type="image/jpeg"
        )
        response = self.client.post(
            reverse("asset_create"),
            self._create_payload(main_photo=too_big),
        )

        assert response.status_code == 200
        assert "supera el tamaño máximo" in response.content.decode()

    def test_valid_jpeg_main_photo_is_accepted_and_reencoded(self):
        good = SimpleUploadedFile("foto.jpg", real_jpeg_bytes(), content_type="image/jpeg")
        response = self.client.post(
            reverse("asset_create"),
            self._create_payload(main_photo=good),
            follow=True,
        )

        assert response.status_code == 200
        # .unscoped(): CurrentCompanyMiddleware already reset the tenant
        # contextvar once the client request finished (apps/core/tenancy.py)
        # — the scoped default manager would see nothing here.
        asset = Asset.objects.unscoped().get(code="FLOW-99")
        assert asset.main_photo.name
        # Re-encoded through Pillow, never stored under the uploaded filename.
        assert "foto" not in asset.main_photo.name

    def test_decompression_bomb_main_photo_is_rejected_in_spanish(self):
        """Security review finding: on-disk size is not decode-time cost — a
        sub-1MB solid-color PNG can decode to gigabytes of native memory.
        Must be rejected by pixel count before Pillow ever decodes it.
        """
        bomb = SimpleUploadedFile(
            "bomb.png", decompression_bomb_png_bytes(), content_type="image/png"
        )

        response = self.client.post(
            reverse("asset_create"),
            self._create_payload(main_photo=bomb),
        )

        assert response.status_code == 200
        assert "demasiado grande" in response.content.decode()
        assert not Asset.objects.unscoped().filter(code="FLOW-99").exists()

    def test_decompression_bomb_document_is_rejected_in_spanish(self):
        asset = AssetFactory(company=self.company)
        bomb = SimpleUploadedFile(
            "bomb.png", decompression_bomb_png_bytes(), content_type="image/png"
        )

        response = self.client.post(
            reverse("assetdocument_upload", args=[asset.pk]),
            {"kind": "manual", "name": "Manual", "file": bomb},
            follow=True,
        )

        assert response.status_code == 200
        assert "demasiado grande" in response.content.decode()
        assert not AssetDocument.objects.unscoped().filter(asset=asset).exists()

    def test_forbidden_extension_on_document_is_rejected_in_spanish(self):
        asset = AssetFactory(company=self.company)
        malicious = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")

        response = self.client.post(
            reverse("assetdocument_upload", args=[asset.pk]),
            {"kind": "manual", "name": "Manual", "file": malicious},
            follow=True,
        )

        assert response.status_code == 200
        assert "Formato no permitido" in response.content.decode()
        assert not AssetDocument.objects.unscoped().filter(asset=asset).exists()

    def test_oversized_document_is_rejected_in_spanish(self):
        asset = AssetFactory(company=self.company)
        too_big = SimpleUploadedFile(
            "manual.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024), content_type="application/pdf"
        )

        response = self.client.post(
            reverse("assetdocument_upload", args=[asset.pk]),
            {"kind": "manual", "name": "Manual", "file": too_big},
            follow=True,
        )

        assert response.status_code == 200
        assert "supera el tamaño máximo" in response.content.decode()
        assert not AssetDocument.objects.unscoped().filter(asset=asset).exists()
