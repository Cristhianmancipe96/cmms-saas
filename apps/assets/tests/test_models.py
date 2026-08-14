import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.tests.factories import CompanyFactory
from apps.assets.models import Asset, AssetHasDocumentsError
from apps.assets.tests.factories import AssetDocumentFactory, AssetFactory


class AssetCodeUniquenessTests(TestCase):
    """Acceptance criterion 1: the same code can exist in two different
    companies, but must be unique within one company.
    """

    def test_same_code_allowed_across_two_companies(self):
        company_a = CompanyFactory()
        company_b = CompanyFactory()

        AssetFactory(company=company_a, code="FLOW-01")
        AssetFactory(company=company_b, code="FLOW-01")

        assert Asset.objects.unscoped().filter(code="FLOW-01").count() == 2

    def test_duplicate_code_within_one_company_is_rejected(self):
        company = CompanyFactory()
        AssetFactory(company=company, code="FLOW-01")

        with pytest.raises(IntegrityError), transaction.atomic():
            AssetFactory(company=company, code="FLOW-01")


class AssetDeletionGuardTests(TestCase):
    """Acceptance criterion 7: an asset with any document attached cannot be
    hard-deleted — only dado_de_baja. Enforced at the model layer too, not
    just the view, so no code path (admin, shell, future service) can skip it.
    """

    def test_delete_raises_when_documents_attached(self):
        asset = AssetFactory()
        AssetDocumentFactory(asset=asset)

        with pytest.raises(AssetHasDocumentsError):
            asset.delete()

        assert Asset.objects.unscoped().filter(pk=asset.pk).exists()

    def test_delete_succeeds_when_no_documents(self):
        asset = AssetFactory()

        asset.delete()

        assert not Asset.objects.unscoped().filter(pk=asset.pk).exists()


class AssetSpecsStorageTests(TestCase):
    def test_specs_list_order_survives_a_db_round_trip(self):
        ordered_specs = [
            {"key": "Voltaje", "value": "220V"},
            {"key": "Potencia", "value": "5 HP"},
            {"key": "Peso", "value": "100 kg"},
        ]
        asset = AssetFactory(specs=ordered_specs)

        # .unscoped(): a plain model TestCase never sets the tenant
        # contextvar (only CurrentCompanyMiddleware does, on a real
        # request) — the scoped default manager would see nothing here.
        reloaded = Asset.objects.unscoped().get(pk=asset.pk)

        assert reloaded.specs == ordered_specs
