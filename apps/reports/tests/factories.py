import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import (
    CompanyFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.reports.models import NotificationLog
from apps.workorders.models import WorkOrder
from apps.workorders.tests.factories import WorkOrderChecklistItemFactory, WorkOrderFactory


class NotificationLogFactory(DjangoModelFactory):
    class Meta:
        model = NotificationLog

    company = factory.SubFactory(CompanyFactory)
    channel = NotificationLog.Channel.EMAIL
    kind = NotificationLog.Kind.ASSET_RECORD
    recipient = factory.Sequence(lambda n: f"destino{n}@example.com")
    subject = "Hoja de vida"
    status = NotificationLog.Status.SENT


def executed_work_order(
    *,
    company=None,
    asset=None,
    technician=None,
    supervisor=None,
    verified: bool = True,
    with_items: bool = True,
) -> WorkOrder:
    """A work order that has actually been done — the only kind with a report.

    Written straight into the finished state rather than driven through
    `services.transition`: the state machine is brief 05's subject and has its
    own exhaustive tests, and a report test that first has to assign, start and
    tick a checklist is a report test that fails for state-machine reasons.
    The fields it would have written are all set here, including the two the
    evidence block is judged on (`completed_by`, `verified_by`).

    The order of the steps below is not cosmetic: the checklist rows go in
    while the work order is still `terminada`, because a `verificada` one
    refuses every child write (`WorkOrderSealedError`). Sealing last is what
    the real verify transition does too.
    """
    company = company or CompanyFactory()
    asset = asset or AssetFactory(company=company)
    technician = technician or TechnicianUserFactory(company=company)
    supervisor = supervisor or SupervisorUserFactory(company=company)
    now = timezone.now()

    work_order = WorkOrderFactory(
        asset=asset,
        assigned_to=technician,
        status=WorkOrder.Status.TERMINADA,
        started_at=now,
        finished_at=now,
        completed_by=technician,
        work_done="Se cambió el rodamiento del eje principal y se lubricó la cadena.",
        downtime_minutes=45,
        labor_cost_cop=120000,
        parts_cost_cop=380000,
    )

    if with_items:
        WorkOrderChecklistItemFactory(
            work_order=work_order,
            order=1,
            text="Revisar nivel de aceite",
            result="ok",
        )
        WorkOrderChecklistItemFactory(
            work_order=work_order,
            order=2,
            text="Medir presión de aire",
            item_type="numeric",
            unit="bar",
            min_value="5.00",
            max_value="7.00",
            numeric_value="8.20",
            result="falla",
            note="Regulador descalibrado.",
        )

    if verified:
        work_order.verified_by = supervisor
        work_order.verified_at = now
        work_order.status = WorkOrder.Status.VERIFICADA
        work_order.save(update_fields=["verified_by", "verified_at", "status", "updated_at"])
    return work_order
