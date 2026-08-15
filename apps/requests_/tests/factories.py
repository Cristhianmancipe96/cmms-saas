import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import TechnicianUserFactory
from apps.assets.tests.factories import AssetFactory
from apps.requests_.models import MaintenanceRequest


class MaintenanceRequestFactory(DjangoModelFactory):
    class Meta:
        model = MaintenanceRequest

    company = factory.SelfAttribute("asset.company")
    asset = factory.SubFactory(AssetFactory)
    reported_by = factory.SubFactory(
        TechnicianUserFactory, company=factory.SelfAttribute("..asset.company")
    )
    description = "La banda hace un ruido fuerte y se detiene sola."
    status = MaintenanceRequest.Status.NUEVA
