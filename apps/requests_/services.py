"""Creating a failure report, and the two decisions a supervisor makes about it.

`convert` is the interesting one, and the only rule it exists to keep is the
brief's: **a request never produces two work orders.** Three independent things
say so, in the order a race would meet them:

1. `select_for_update` on the request row. The second click blocks until the
   first commits, then re-reads and sees `convertida`.
2. The status check on the *re-read* row (never on the caller's copy, which was
   loaded when the page rendered and may be minutes old on a plant-floor
   connection).
3. `UNIQUE(source_request_id)` on the work-order table. If both of the above
   were ever bypassed — a shell, a future call site, a bug — Postgres refuses
   the insert. `IntegrityError` is caught and answered with the work order that
   already exists, because from the operator's point of view a second click on
   «Convertir» means "take me to the OT", not "explode".

And the second click is *idempotent*, not an error: it lands on the same work
order the first one created. A double tap on a phone is not a mistake worth a
red message.

Every read here goes through `.unscoped()` with an explicit id filter and
restores tenant isolation by comparing `company_id` against the acting user's,
for the reason spelled out at the top of apps/workorders/services.py: a
`CompanyScopedManager` returns nothing at all when no request has set the
tenant contextvar, and a rule that silently passes outside a request is not a
rule.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core import webhooks
from apps.requests_.models import MaintenanceRequest
from apps.workorders.models import WorkOrder

# --- Errors -----------------------------------------------------------------


class RequestError(Exception):
    """Base class for every refusal here. The message is the Spanish sentence
    the operator should read — same convention as apps/workorders/services.py."""


class NotAllowed(RequestError):
    """The action exists, but not for this user (or not for this company)."""


class InvalidStatus(RequestError):
    """The request has already been decided."""


REVIEWER_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR)

# What the audit log keeps about a request decision.
AUDITED_FIELDS = ("status", "reviewed_by", "review_note")


def may_review(user) -> bool:
    """Who converts and rejects: the people who own the plan of work."""
    return bool(user.is_platform_admin or user.role in REVIEWER_ROLES)


def may_report(user) -> bool:
    """Who reports a failure: anybody with a session and a company.

    Wider than `workorder_services.may_report_failure`, and that is the point
    of this whole app — the office `staff` role may not open a work order, but
    the machine they walk past every morning is still stopped.
    """
    return bool(user.is_authenticated and user.company_id is not None)


# --- Reads ------------------------------------------------------------------


def base_queryset():
    return MaintenanceRequest.objects.select_related(
        "asset", "asset__site", "reported_by", "reviewed_by", "work_order"
    )


def visible_to(user):
    """The rows this person may list.

    Managers see the company's queue; everyone else sees their own reports and
    nothing more. Written as a queryset filter rather than a per-row check so
    the list view cannot forget it.
    """
    queryset = base_queryset()
    if may_review(user):
        return queryset
    return queryset.filter(reported_by=user)


def may_see(request_obj, user) -> bool:
    return may_review(user) or request_obj.reported_by_id == user.pk


# --- Writes -----------------------------------------------------------------


@transaction.atomic
def create_request(*, asset, user, description: str, photo=None, http_request=None):
    """File one report. Audited, and announced to n8n."""
    if not may_report(user):
        raise NotAllowed("Necesitas una cuenta de la empresa para reportar una falla.")
    if asset.company_id != user.company_id:
        raise NotAllowed("Ese equipo no pertenece a tu empresa.")

    request_obj = MaintenanceRequest.objects.create(
        company_id=asset.company_id,
        asset=asset,
        reported_by=user,
        description=description,
        photo=photo or "",
    )
    audit.record(
        action=AuditLog.Action.CREATE,
        instance=request_obj,
        user=user,
        changes=audit.created(request_obj, ("asset", "description", "status")),
        request=http_request,
    )
    webhooks.emit(
        webhooks.EVENT_REQUEST_CREATED,
        company_id=request_obj.company_id,
        object_type="solicitud",
        object_id=request_obj.pk,
        data={"equipo_id": request_obj.asset_id, "estado": request_obj.status},
    )
    return request_obj


def _locked(request_obj, user) -> MaintenanceRequest:
    """Re-read the row under a lock, then answer the tenant question."""
    locked = (
        MaintenanceRequest.objects.unscoped()
        .select_for_update()
        .filter(pk=request_obj.pk)
        .first()
    )
    if locked is None:
        raise NotAllowed("Esa solicitud ya no existe.")
    if not user.is_platform_admin and locked.company_id != user.company_id:
        raise NotAllowed("Esa solicitud no pertenece a tu empresa.")
    if not may_review(user):
        raise NotAllowed("Solo un supervisor o un administrador puede decidir una solicitud.")
    return locked


def existing_work_order(request_obj) -> WorkOrder | None:
    return WorkOrder.objects.unscoped().filter(source_request_id=request_obj.pk).first()


@transaction.atomic
def convert(request_obj, *, user, priority=None, http_request=None) -> WorkOrder:
    """Turn a report into a corrective work order. Atomic and idempotent."""
    locked = _locked(request_obj, user)

    already = existing_work_order(locked)
    if already is not None:
        # The second click of a double tap. Same OT, no second row, no error.
        return already
    if locked.status != MaintenanceRequest.Status.NUEVA:
        raise InvalidStatus("Esta solicitud ya fue rechazada, así que no se puede convertir.")

    try:
        work_order = WorkOrder.objects.create(
            company_id=locked.company_id,
            asset_id=locked.asset_id,
            source_request=locked,
            type=WorkOrder.Type.CORRECTIVO,
            origin=WorkOrder.Origin.SOLICITUD,
            status=WorkOrder.Status.ABIERTA,
            priority=priority or WorkOrder.Priority.ALTA,
            # Copied, not referenced: the work order must still describe the
            # failure it was opened for even if the request text is later
            # unreachable, exactly like the checklist snapshot in brief 05.
            failure_description=locked.description,
        )
    except IntegrityError:
        # UNIQUE(source_request_id) fired: somebody else got there first, in a
        # transaction our lock could not see (a shell, a future call site).
        # The answer is still "here is the OT", never a duplicate.
        existing = existing_work_order(locked)
        if existing is None:  # pragma: no cover — only reachable if the row vanished
            raise
        return existing

    before = {"status": MaintenanceRequest.Status.NUEVA, "reviewed_by": None}
    locked.status = MaintenanceRequest.Status.CONVERTIDA
    locked.reviewed_by = user
    locked.reviewed_at = timezone.now()
    locked.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

    audit.record(
        action=AuditLog.Action.TRANSITION,
        instance=locked,
        user=user,
        changes={
            **audit.diff(
                before,
                {"status": locked.status, "reviewed_by": user.pk},
                instance=locked,
            ),
            **audit.note(orden_de_trabajo=work_order.pk),
        },
        request=http_request,
    )
    return work_order


@transaction.atomic
def reject(request_obj, *, user, note: str, http_request=None) -> MaintenanceRequest:
    """Refuse a report — with a reason, always."""
    locked = _locked(request_obj, user)
    if locked.status != MaintenanceRequest.Status.NUEVA:
        raise InvalidStatus("Esta solicitud ya fue decidida.")
    reason = (note or "").strip()
    if not reason:
        raise RequestError("Escribe el motivo del rechazo.")

    before = {"status": locked.status, "review_note": locked.review_note}
    locked.status = MaintenanceRequest.Status.RECHAZADA
    locked.review_note = reason
    locked.reviewed_by = user
    locked.reviewed_at = timezone.now()
    locked.save(
        update_fields=["status", "review_note", "reviewed_by", "reviewed_at", "updated_at"]
    )

    audit.record(
        action=AuditLog.Action.TRANSITION,
        instance=locked,
        user=user,
        changes=audit.diff(
            before,
            {"status": locked.status, "review_note": locked.review_note},
            instance=locked,
        ),
        request=http_request,
    )
    return locked
