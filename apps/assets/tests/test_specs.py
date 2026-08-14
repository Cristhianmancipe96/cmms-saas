from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory, SiteFactory
from apps.assets.models import Asset
from apps.assets.tests.factories import AssetCategoryFactory


class SpecsOrderRoundTripTests(TestCase):
    """Acceptance criterion 6: specs survive a create -> edit round trip
    preserving key order. Postgres jsonb does NOT preserve dict key order —
    this is exactly why specs are stored as an ordered list of pairs.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.site = SiteFactory(company=self.company)
        self.category = AssetCategoryFactory(company=self.company)
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)

    def _base_payload(self, **overrides):
        payload = {
            "site": self.site.pk,
            "category": self.category.pk,
            "code": "FLOW-01",
            "name": "Empacadora",
            "brand": "Flowpac",
            "model": "FP-2000",
            "serial_number": "SN-1",
            "criticality": "alta",
            "location_detail": "Línea 1",
        }
        payload.update(overrides)
        return payload

    def test_create_stores_specs_in_submitted_order(self):
        payload = self._base_payload(
            spec_key=["Voltaje", "Potencia", "Peso"],
            spec_value=["220V", "5 HP", "100 kg"],
        )

        self.client.post(reverse("asset_create"), payload, follow=True)

        # .unscoped(): the tenant contextvar is already reset once the
        # client request has finished (apps/core/tenancy.py).
        asset = Asset.objects.unscoped().get(code="FLOW-01")
        assert asset.specs == [
            {"key": "Voltaje", "value": "220V"},
            {"key": "Potencia", "value": "5 HP"},
            {"key": "Peso", "value": "100 kg"},
        ]

    def test_edit_form_renders_specs_in_stored_order(self):
        asset = Asset.objects.create(
            company=self.company,
            site=self.site,
            category=self.category,
            code="FLOW-02",
            name="Empacadora 2",
            specs=[
                {"key": "Voltaje", "value": "220V"},
                {"key": "Potencia", "value": "5 HP"},
                {"key": "Peso", "value": "100 kg"},
            ],
        )

        response = self.client.get(reverse("asset_update", args=[asset.pk]))
        content = response.content.decode()

        assert content.index("Voltaje") < content.index("Potencia") < content.index("Peso")

    def test_edit_round_trip_preserves_reordered_specs(self):
        asset = Asset.objects.create(
            company=self.company,
            site=self.site,
            category=self.category,
            code="FLOW-03",
            name="Empacadora 3",
            specs=[
                {"key": "Voltaje", "value": "220V"},
                {"key": "Potencia", "value": "5 HP"},
            ],
        )

        payload = self._base_payload(
            code="FLOW-03",
            name="Empacadora 3",
            spec_key=["Potencia", "Voltaje", "Peso"],
            spec_value=["5 HP", "220V", "100 kg"],
        )
        self.client.post(reverse("asset_update", args=[asset.pk]), payload, follow=True)

        asset.refresh_from_db()
        assert asset.specs == [
            {"key": "Potencia", "value": "5 HP"},
            {"key": "Voltaje", "value": "220V"},
            {"key": "Peso", "value": "100 kg"},
        ]

    def test_empty_spec_rows_are_dropped(self):
        payload = self._base_payload(
            code="FLOW-04",
            spec_key=["Voltaje", ""],
            spec_value=["220V", ""],
        )

        self.client.post(reverse("asset_create"), payload, follow=True)

        asset = Asset.objects.unscoped().get(code="FLOW-04")
        assert asset.specs == [{"key": "Voltaje", "value": "220V"}]
