"""The work-order state machine and the checklist snapshot.

`transition(work_order, action, user, **payload)` is the ONE way a work order
changes state. Views, the admin, a shell session and (later) the n8n webhook
all go through it, so the permission×state matrix exists in exactly one place
and can be tested exhaustively (acceptance criterion 1) without a browser.

Two rules the matrix encodes are not conveniences, they are the product's
audit promise (CLAUDE.md rules 3 and 4):

- **Whoever executes never verifies.** Not "usually": the check compares user
  identities, so a supervisor who assigned a work order to themselves and
  completed it is refused by exactly the same line of code that refuses a
  technician.
- **Verifying seals the row.** The immutability guards live on the models;
  this module only decides who may push the button.

Every read here goes through `.unscoped()` with an explicit id filter, and
every write uses `_id` attributes. Same reason as apps/checklists/services.py:
a `CompanyScopedManager` returns *nothing* when no request set the tenant
contextvar, so `work_order.checklist_items.all()` would report "no required
items pending" from a management command and wave an empty work order through
as complete. Tenant isolation is restored explicitly, by comparing
`company_id` against the acting user's, at the top of every entry point.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.assets.models import Asset
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem
from apps.maintenance.models import MaintenancePlan, MeterReading, record_reading
from apps.workorders.models import (
    SEALED_MESSAGE,
    WorkOrder,
    WorkOrderChecklistItem,
    WorkOrderPhoto,
)

# --- Errors -----------------------------------------------------------------


class WorkOrderError(Exception):
    """Base class for every refusal in this module.

    The message is already the Spanish sentence the operator should read:
    keeping it next to the rule is what stops the four call sites (list view,
    detail view, execution screen, HTMX item save) from inventing four
    different wordings for the same refusal.
    """


class InvalidTransition(WorkOrderError):
    """The action does not exist from the work order's current state."""


class NotAllowed(WorkOrderError):
    """The action exists, but not for this user."""


class IncompleteChecklist(WorkOrderError):
    """Completion attempted with required checklist items unanswered."""


# --- Actions ----------------------------------------------------------------

ASSIGN = "assign"
START = "start"
COMPLETE = "complete"
VERIFY = "verify"
CANCEL = "cancel"

ACTION_VERBS = {
    ASSIGN: "asignar",
    START: "iniciar",
    COMPLETE: "terminar",
    VERIFY: "verificar",
    CANCEL: "cancelar",
}

MANAGER_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR)

# Who may carry a work order: the shop floor plus the people who supervise it.
# `staff` is the office role (invoices, paperwork) and is deliberately absent —
# the same line drawn for hour-meter readings in apps/maintenance/views.py.
ASSIGNABLE_ROLES = (User.Role.TECHNICIAN, User.Role.SUPERVISOR, User.Role.ADMIN)

# Who may open a corrective work order. Reporting a breakdown is shop-floor
# work: the person who finds the broken machine is usually the technician
# standing in front of it. Office `staff` report failures through brief 08's
# «solicitud» flow instead. Lives here, not in a views module, so the asset
# screen can ask the same question without importing another app's views.
REPORTER_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN)


def may_report_failure(user) -> bool:
    return bool(user.is_platform_admin or user.role in REPORTER_ROLES)


def is_manager(user) -> bool:
    return bool(user.is_platform_admin or user.role in MANAGER_ROLES)


def _requires_manager(work_order: WorkOrder, user, verb: str) -> str | None:
    if is_manager(user):
        return None
    return f"Solo un supervisor o un administrador puede {verb} una OT."


def _requires_assignee(work_order: WorkOrder, user, verb: str) -> str | None:
    if work_order.assigned_to_id is not None and work_order.assigned_to_id == user.pk:
        return None
    # Deliberately not "…or a supervisor". A supervisor who wants to execute
    # assigns the work order to themselves first, which records them as the
    # executor and — by CLAUDE.md rule 3 — costs them the right to verify it.
    return f"Solo el técnico asignado puede {verb} esta OT."


def _may_verify(work_order: WorkOrder, user, verb: str) -> str | None:
    if not is_manager(user):
        return "Solo un supervisor o un administrador puede verificar una OT."
    if work_order.completed_by_id is None:
        # Unreachable through `complete`, which always stamps the executor.
        # Refusing is the safe direction: without a recorded executor there is
        # no way to prove the person verifying is not the person who worked.
        return "Esta OT no registra quién la ejecutó, así que no se puede verificar."
    if work_order.completed_by_id == user.pk:
        return "Quien ejecuta una OT no puede verificarla. Pídelo a otro supervisor."
    return None


@dataclass(frozen=True)
class TransitionRule:
    from_statuses: tuple[str, ...]
    to_status: str
    check: Callable[[WorkOrder, User, str], str | None]


# The matrix. Reading it top to bottom is the spec:
#   abierta ─assign→ asignada ─start→ en_progreso ─complete→ terminada ─verify→ verificada
# with `cancel` available from anything that is not already finished, and
# nothing at all available out of `verificada` or `cancelada`.
TRANSITIONS: dict[str, TransitionRule] = {
    # Re-assigning a work order that has not started yet is the same action,
    # so a supervisor can fix a wrong assignee without cancelling and
    # recreating. Once work is under way the assignee is frozen — that is what
    # makes "who executed" answerable.
    ASSIGN: TransitionRule(
        from_statuses=(WorkOrder.Status.ABIERTA, WorkOrder.Status.ASIGNADA),
        to_status=WorkOrder.Status.ASIGNADA,
        check=_requires_manager,
    ),
    START: TransitionRule(
        from_statuses=(WorkOrder.Status.ASIGNADA,),
        to_status=WorkOrder.Status.EN_PROGRESO,
        check=_requires_assignee,
    ),
    COMPLETE: TransitionRule(
        from_statuses=(WorkOrder.Status.EN_PROGRESO,),
        to_status=WorkOrder.Status.TERMINADA,
        check=_requires_assignee,
    ),
    VERIFY: TransitionRule(
        from_statuses=(WorkOrder.Status.TERMINADA,),
        to_status=WorkOrder.Status.VERIFICADA,
        check=_may_verify,
    ),
    CANCEL: TransitionRule(
        from_statuses=(
            WorkOrder.Status.ABIERTA,
            WorkOrder.Status.ASIGNADA,
            WorkOrder.Status.EN_PROGRESO,
            WorkOrder.Status.TERMINADA,
        ),
        to_status=WorkOrder.Status.CANCELADA,
        check=_requires_manager,
    ),
}


# --- Reads that must work outside a request ---------------------------------


def checklist_items(work_order: WorkOrder):
    return (
        WorkOrderChecklistItem.objects.unscoped()
        .filter(work_order_id=work_order.pk)
        .order_by("order")
    )


def photos(work_order: WorkOrder):
    return (
        WorkOrderPhoto.objects.unscoped()
        .filter(work_order_id=work_order.pk)
        .select_related("taken_by")
        .order_by("taken_at", "id")
    )


def pending_required_items(work_order: WorkOrder) -> list[WorkOrderChecklistItem]:
    """Required items still unanswered — what blocks `complete`."""
    return [item for item in checklist_items(work_order) if item.required and not item.is_answered]


def asset_tracks_meter(asset_id: int) -> bool:
    """Whether closing a work order on this machine should ask for the hours.

    True when the machine has an active meter-driven plan (its schedule
    depends on the number) or already has readings (someone is keeping the
    series, so a gap in it is a loss).
    """
    has_meter_plan = (
        MaintenancePlan.objects.unscoped()
        .filter(
            asset_id=asset_id,
            frequency_type=MaintenancePlan.FrequencyType.METER,
            is_active=True,
        )
        .exists()
    )
    return has_meter_plan or MeterReading.objects.unscoped().filter(asset_id=asset_id).exists()


# --- Snapshot ---------------------------------------------------------------


@transaction.atomic
def snapshot_checklist(
    work_order: WorkOrder, template: ChecklistTemplate | None
) -> int:
    """Freeze `template`'s items onto the work order (build item 2).

    Copies, not references: acceptance criterion 4 asks that editing the
    template afterwards leave the work order byte-identical, and the only way
    to guarantee that for a row nobody is watching is to not point at the
    template at all. `checklist_template` is recorded alongside as provenance —
    it answers "which version was this?" without being read at execution time.

    Returns the number of items copied. A corrective work order with no plan
    and no template legitimately gets zero.
    """
    if template is None:
        return 0
    # bulk_create writes straight to SQL and never calls
    # WorkOrderChecklistItem.save(), so the model-level seal does not see it.
    # This is the only bulk path into that table; it asks the question itself.
    if work_order.status == WorkOrder.Status.VERIFICADA:
        raise NotAllowed(SEALED_MESSAGE)

    source_items = (
        ChecklistTemplateItem.objects.unscoped().filter(template_id=template.pk).order_by("order")
    )
    snapshot = [
        WorkOrderChecklistItem(
            company_id=work_order.company_id,
            work_order_id=work_order.pk,
            order=item.order,
            text=item.text,
            item_type=item.item_type,
            unit=item.unit,
            min_value=item.min_value,
            max_value=item.max_value,
            required=item.required,
        )
        for item in source_items
    ]
    WorkOrderChecklistItem.objects.bulk_create(snapshot)

    work_order.checklist_template_id = template.pk
    work_order.save(update_fields=["checklist_template", "updated_at"])
    return len(snapshot)


# --- Filling the checklist --------------------------------------------------


def _assert_item_belongs(work_order: WorkOrder, item: WorkOrderChecklistItem) -> None:
    if item.work_order_id != work_order.pk or item.company_id != work_order.company_id:
        raise NotAllowed("Ese ítem no pertenece a esta OT.")


def _resolve_numeric(
    item: WorkOrderChecklistItem, numeric_value: Decimal | None
) -> tuple[str, Decimal]:
    """Acceptance criterion 5: a measurement outside the range IS a failure.

    The technician records what the gauge says; whether that counts as a fault
    is arithmetic, not an opinion, so the result is derived here and never
    taken from the form. Items whose range was left open (both bounds null)
    can only ever read OK — checklist templates reject numeric items without a
    range, so that shape only exists in data written before that rule.
    """
    if numeric_value is None:
        raise WorkOrderError("Escribe el valor medido.")
    below = item.min_value is not None and numeric_value < item.min_value
    above = item.max_value is not None and numeric_value > item.max_value
    result = (
        WorkOrderChecklistItem.Result.FALLA
        if below or above
        else WorkOrderChecklistItem.Result.OK
    )
    return result, numeric_value


@transaction.atomic
def record_item_result(
    work_order: WorkOrder,
    item: WorkOrderChecklistItem,
    *,
    user,
    result: str = "",
    numeric_value: Decimal | None = None,
    note: str = "",
) -> WorkOrderChecklistItem:
    """Save one checklist answer — the write behind every HTMX tap.

    Per-item rather than one big form on purpose: a technician on a plant
    floor loses the network mid-inspection, and half a checklist already
    stored beats a whole one lost.
    """
    _assert_item_belongs(work_order, item)
    if work_order.status != WorkOrder.Status.EN_PROGRESO:
        raise NotAllowed("Solo se puede llenar el checklist de una OT en progreso.")
    if work_order.assigned_to_id != user.pk:
        raise NotAllowed("Solo el técnico asignado puede llenar este checklist.")

    item.note = note.strip()

    if item.item_type == WorkOrderChecklistItem.ItemType.TEXT:
        # A text item has nothing to press: its note is its answer.
        item.result = ""
        item.numeric_value = None
    elif item.item_type == WorkOrderChecklistItem.ItemType.NUMERIC:
        if result == WorkOrderChecklistItem.Result.NA:
            item.result = WorkOrderChecklistItem.Result.NA
            item.numeric_value = None
        else:
            item.result, item.numeric_value = _resolve_numeric(item, numeric_value)
    else:
        if result not in WorkOrderChecklistItem.Result.values:
            raise WorkOrderError("Responde OK, Falla o N/A.")
        item.result = result
        item.numeric_value = None

    item.save(update_fields=["result", "numeric_value", "note"])
    return item


# --- The state machine ------------------------------------------------------


def _apply_assign(work_order: WorkOrder, user, payload: dict) -> list[str]:
    assignee = payload.get("assignee")
    if assignee is None:
        raise WorkOrderError("Elige a quién se le asigna la OT.")
    if assignee.company_id != work_order.company_id:
        raise NotAllowed("Esa persona no pertenece a la empresa de la OT.")
    if not assignee.is_active or assignee.role not in ASSIGNABLE_ROLES:
        raise NotAllowed("Esa persona no puede recibir órdenes de trabajo.")
    work_order.assigned_to_id = assignee.pk
    return ["assigned_to"]


def _apply_start(work_order: WorkOrder, user, payload: dict) -> list[str]:
    work_order.started_at = timezone.now()
    return ["started_at"]


def _apply_complete(work_order: WorkOrder, user, payload: dict) -> list[str]:
    pending = pending_required_items(work_order)
    if pending:
        plural = len(pending) > 1
        raise IncompleteChecklist(
            f"{'Faltan' if plural else 'Falta'} {len(pending)} "
            f"ítem{'s' if plural else ''} obligatorio{'s' if plural else ''} "
            "del checklist por responder."
        )

    work_order.work_done = payload.get("work_done", work_order.work_done)
    work_order.downtime_minutes = payload.get("downtime_minutes", work_order.downtime_minutes)
    work_order.labor_cost_cop = payload.get("labor_cost_cop", work_order.labor_cost_cop)
    work_order.parts_cost_cop = payload.get("parts_cost_cop", work_order.parts_cost_cop)
    work_order.finished_at = timezone.now()
    work_order.completed_by_id = user.pk

    reading_hours = payload.get("meter_reading_hours")
    if reading_hours is not None:
        # Build item 7. Goes through record_reading, so this write serializes
        # on the asset row exactly like the one from the horómetro panel — two
        # work orders closed on the same machine at the same second cannot
        # both slip past the "a meter never runs backwards" check.
        asset = Asset.objects.unscoped().get(pk=work_order.asset_id)
        try:
            record_reading(
                asset=asset,
                reading_hours=reading_hours,
                source=MeterReading.Source.WORK_ORDER,
                recorded_by=user,
            )
        except ValidationError as error:
            # Re-raised as a WorkOrderError so this module keeps ONE refusal
            # type. The views catch WorkOrderError and render the message; a
            # stray ValidationError escaping from here would reach the
            # technician as a 500 instead of "la lectura no puede ser menor…".
            raise WorkOrderError(" ".join(error.messages)) from error

    return [
        "work_done",
        "downtime_minutes",
        "labor_cost_cop",
        "parts_cost_cop",
        "finished_at",
        "completed_by",
    ]


def _apply_verify(work_order: WorkOrder, user, payload: dict) -> list[str]:
    work_order.verified_by_id = user.pk
    work_order.verified_at = timezone.now()
    return ["verified_by", "verified_at"]


def _apply_cancel(work_order: WorkOrder, user, payload: dict) -> list[str]:
    reason = (payload.get("reason") or "").strip()
    if not reason:
        raise WorkOrderError("Indica el motivo de la cancelación.")
    work_order.cancel_reason = reason
    return ["cancel_reason"]


APPLY = {
    ASSIGN: _apply_assign,
    START: _apply_start,
    COMPLETE: _apply_complete,
    VERIFY: _apply_verify,
    CANCEL: _apply_cancel,
}


@transaction.atomic
def transition(work_order: WorkOrder, action: str, user, **payload) -> WorkOrder:
    """Move a work order through the matrix, or refuse in Spanish.

    Re-reads the row under `select_for_update` before deciding anything: the
    caller's copy was loaded who-knows-how-long ago, and a phone on a bad
    connection double-taps. Two concurrent `verify` calls would otherwise both
    see `terminada`, both pass the check, and both write — the second one
    silently overwriting who verified.
    """
    rule = TRANSITIONS.get(action)
    if rule is None:
        raise InvalidTransition(f"Acción desconocida: {action}.")

    locked = WorkOrder.objects.unscoped().select_for_update().filter(pk=work_order.pk).first()
    if locked is None:
        raise InvalidTransition("Esa OT ya no existe.")

    # The reads above are unscoped so this module also works from a command;
    # tenant isolation is therefore restored here, explicitly, instead of
    # being inherited from a contextvar that may not be set.
    if not user.is_platform_admin and locked.company_id != user.company_id:
        raise NotAllowed("Esa OT no pertenece a tu empresa.")

    if locked.status not in rule.from_statuses:
        status_label = WorkOrder.Status(locked.status).label.lower()
        raise InvalidTransition(
            f"No se puede {ACTION_VERBS[action]} una OT {status_label}."
        )

    denial = rule.check(locked, user, ACTION_VERBS[action])
    if denial:
        raise NotAllowed(denial)

    changed_fields = APPLY[action](locked, user, payload)
    locked.status = rule.to_status
    locked.save(update_fields=[*changed_fields, "status", "updated_at"])
    return locked


def annotate_overdue(work_orders, *, today=None) -> list[WorkOrder]:
    """Attach `.overdue` to each row for the templates.

    Django templates cannot call `is_overdue(today)`, and letting each screen
    re-derive "late" with its own `{% if %}` is how two screens end up
    disagreeing about the same work order. Same shape as
    `maintenance.services.annotate_due_state`.
    """
    today = today or timezone.localdate()
    rows = list(work_orders)
    for work_order in rows:
        work_order.overdue = work_order.is_overdue(today)
    return rows


def available_actions(work_order: WorkOrder, user) -> list[str]:
    """Which buttons this user should see on this work order.

    The screens ask this instead of re-deriving the rules in a template: a
    button that renders and then refuses is a bug report waiting to happen,
    and a second copy of the matrix is a second place to get it wrong.
    """
    if not user.is_platform_admin and work_order.company_id != user.company_id:
        return []
    return [
        action
        for action, rule in TRANSITIONS.items()
        if work_order.status in rule.from_statuses
        and rule.check(work_order, user, ACTION_VERBS[action]) is None
    ]
