import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import CompanyFactory, SiteFactory, UserFactory
from apps.assets.models import Asset, AssetCategory, AssetDocument

FLOWPAC_SPECS = [
    {"key": "Potencia del motor", "value": "5.5 HP"},
    {"key": "Velocidad máxima", "value": "120 paq/min"},
    {"key": "Voltaje", "value": "220V trifásico"},
    {"key": "Ancho de película", "value": "400 mm"},
    {"key": "Presión de aire", "value": "6 bar"},
    {"key": "Peso", "value": "850 kg"},
]


class AssetCategoryFactory(DjangoModelFactory):
    class Meta:
        model = AssetCategory

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Empacadora tipo {n}")


class AssetFactory(DjangoModelFactory):
    class Meta:
        model = Asset

    company = factory.SubFactory(CompanyFactory)
    site = factory.SubFactory(SiteFactory, company=factory.SelfAttribute("..company"))
    category = factory.SubFactory(AssetCategoryFactory, company=factory.SelfAttribute("..company"))
    code = factory.Sequence(lambda n: f"FLOW-{n:02d}")
    name = factory.Sequence(lambda n: f"Empacadora Flowpac {n}")
    brand = "Flowpac"
    model = "FP-2000"
    serial_number = factory.Sequence(lambda n: f"SN-{n:06d}")
    criticality = Asset.Criticality.ALTA
    status = Asset.Status.OPERATIVO
    location_detail = "Línea 1"
    specs = factory.LazyFunction(lambda: [dict(pair) for pair in FLOWPAC_SPECS])
    created_by = factory.SubFactory(UserFactory, company=factory.SelfAttribute("..company"))


class AssetDocumentFactory(DjangoModelFactory):
    class Meta:
        model = AssetDocument

    company = factory.SelfAttribute("asset.company")
    asset = factory.SubFactory(AssetFactory)
    kind = AssetDocument.Kind.MANUAL
    name = factory.Sequence(lambda n: f"Manual {n}")
    file = factory.django.FileField(filename="manual.pdf", data=b"%PDF-1.4 test")
    uploaded_by = factory.SubFactory(UserFactory, company=factory.SelfAttribute("..asset.company"))
