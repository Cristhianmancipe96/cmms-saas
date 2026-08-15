import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import TechnicianUserFactory
from apps.assets.tests.factories import AssetFactory
from apps.workorders.models import WorkOrder, WorkOrderChecklistItem, WorkOrderPhoto


class WorkOrderFactory(DjangoModelFactory):
    class Meta:
        model = WorkOrder

    company = factory.SelfAttribute("asset.company")
    asset = factory.SubFactory(AssetFactory)
    plan = None
    checklist_template = None
    type = WorkOrder.Type.PREVENTIVO
    origin = WorkOrder.Origin.PLAN
    status = WorkOrder.Status.ABIERTA
    priority = WorkOrder.Priority.MEDIA


class AssignedWorkOrderFactory(WorkOrderFactory):
    """The common starting point for execution tests: assigned to a technician
    of the same company, ready to be started."""

    status = WorkOrder.Status.ASIGNADA
    assigned_to = factory.SubFactory(
        TechnicianUserFactory, company=factory.SelfAttribute("..asset.company")
    )


class WorkOrderChecklistItemFactory(DjangoModelFactory):
    class Meta:
        model = WorkOrderChecklistItem

    company = factory.SelfAttribute("work_order.company")
    work_order = factory.SubFactory(WorkOrderFactory)
    order = factory.Sequence(lambda n: n + 1)
    text = factory.Sequence(lambda n: f"Verificar punto {n}")
    item_type = WorkOrderChecklistItem.ItemType.CHECK
    unit = ""
    min_value = None
    max_value = None
    required = True
    result = ""
    numeric_value = None
    note = ""


class WorkOrderPhotoFactory(DjangoModelFactory):
    class Meta:
        model = WorkOrderPhoto

    company = factory.SelfAttribute("work_order.company")
    work_order = factory.SubFactory(WorkOrderFactory)
    image = factory.django.FileField(filename="evidencia.jpg", data=b"fake-jpeg-bytes")
    caption = "Evidencia"


def lock_template(template, **kwargs) -> WorkOrder:
    """Give a checklist template a real work order, so `is_locked()` is true.

    Brief 03's tests used to force the locked branch with
    `mock.patch.object(ChecklistTemplate, "is_locked", ...)` because work
    orders did not exist yet. They do now, and a mocked lock proves nothing
    about the FK the real lock reads — so the tests create one of these
    instead.
    """
    return WorkOrderFactory(
        asset=AssetFactory(company=template.company),
        checklist_template=template,
        **kwargs,
    )
