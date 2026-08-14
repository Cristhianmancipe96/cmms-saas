import factory
from factory.django import DjangoModelFactory

from apps.assets.tests.factories import AssetFactory
from apps.workorders.models import WorkOrder


class WorkOrderFactory(DjangoModelFactory):
    class Meta:
        model = WorkOrder

    company = factory.SelfAttribute("asset.company")
    asset = factory.SubFactory(AssetFactory)
    plan = None
    type = WorkOrder.Type.PREVENTIVO
    origin = WorkOrder.Origin.PLAN
    status = WorkOrder.Status.ABIERTA
    priority = WorkOrder.Priority.MEDIA
