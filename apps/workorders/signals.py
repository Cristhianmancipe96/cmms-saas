"""`ot_creada` — announced from a `post_save` receiver, not from three call sites.

Work orders are born in three legitimate places: the scheduler
(`maintenance.services._create_work_order`), the manual corrective form
(`views.corrective_create`) and the conversion of a failure report
(`requests_.services.convert`). A brief that adds an event to each of the three
adds a fourth place to forget it. A receiver on the model cannot be forgotten:
whatever creates a work order, the event goes out.

The contrast with `ot_verificada` — emitted from `services.transition` — is
deliberate and is the rule this codebase follows: **the receiver is for facts
with many authors, the service is for facts with exactly one.** `verificada` is
reachable only through the state machine, so putting its event anywhere else
would hide the rule instead of stating it.

Everything downstream is a no-op when `N8N_WEBHOOK_URL` is unset, which is the
normal state in development and in the whole test suite.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core import webhooks
from apps.workorders.models import WorkOrder


@receiver(post_save, sender=WorkOrder, dispatch_uid="workorders.emit_created")
def emit_work_order_created(sender, instance: WorkOrder, created: bool, **kwargs) -> None:
    if not created:
        return
    webhooks.emit(
        webhooks.EVENT_WORK_ORDER_CREATED,
        company_id=instance.company_id,
        object_type="orden_de_trabajo",
        object_id=instance.pk,
        data={
            "equipo_id": instance.asset_id,
            "tipo": instance.type,
            "origen": instance.origin,
            "prioridad": instance.priority,
            "estado": instance.status,
            # A date, not a person: n8n decides *when* to nag, and asks the API
            # who to nag when the time comes.
            #
            # `str`, not `.isoformat()`: a receiver runs on whatever the caller
            # left on the instance, and Django does not coerce an assigned
            # value to a `date` until the row is read back — so
            # `WorkOrder(due_date="2026-01-01")` reaches here as a string and
            # would break the *save* over a webhook field. `str(date)` is
            # already the ISO form, so both paths emit the same thing.
            "fecha_programada": str(instance.due_date) if instance.due_date else None,
            "solicitud_id": instance.source_request_id,
        },
    )
