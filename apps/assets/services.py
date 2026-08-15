"""What a QR scan shows, and to whom.

`/e/<qr_uuid>` is the product's signature screen: a sticker on a machine,
opened by whoever is standing in front of it. That "whoever" is the entire
design problem. The same URL is opened by a technician mid-shift, by a
supervisor at a desk, by an auditor with a visitor badge and no session at
all, and — as soon as one photograph of a label travels — by someone from
another company entirely.

So the audience is resolved ONCE, here, and everything downstream follows
from it. Views ask for the audience; templates render the section that
audience earned. Neither re-derives the rule, because a second copy of
"who may see this machine" is a second place to get tenant isolation wrong.

Two invariants this module exists to keep:

- **Nothing operational escapes the tenant.** Anyone who is not an
  authenticated member of the owning company gets `PLATE`: the machine's own
  code and name, and nothing else. No company name, no status, no
  criticality, no plans, no work orders, no history — and no link carrying
  the asset's primary key.
- **The plate never grows an action.** It is a read whose only button is
  "iniciar sesión". Every write in this product starts from a screen that
  already knows who you are.

Why the plate and not a 404 for a stranger (brief item 4): a QR sticker is
physically public — anyone who can stand in front of the machine can read the
same code and name off the label itself, session or not. Serving the plate to
an out-of-company user makes **the plate they get identical to the anonymous
one** — same template, same two values, nothing that varies with who owns the
machine — so nobody can use a login to learn "this UUID belongs to some other
company". Choosing 404 there would have leaked exactly that.

Note what that claim does *not* say: the two HTTP responses are not identical
byte for byte, and cannot be. They share `base.html`, whose top bar renders
«Salir» and a nav for a logged-in visitor and «Iniciar sesión» for an
anonymous one. That difference is about the *viewer*, not about the machine,
which is the only distinction that would leak anything. What also remains
distinguishable is "this UUID exists" (plate) versus "it does not" (404), and
that is inherent to showing a plate at all — harmless against a uuid4, which
cannot be enumerated.
"""

from django.db.models import F

from apps.accounts.models import User
from apps.maintenance import services as maintenance_services
from apps.workorders import services as workorder_services
from apps.workorders.models import WorkOrder

# Audiences, in order of how much of the machine they get to see.
PLATE = "plate"
TECHNICIAN = "technician"
STAFF = "staff"
MANAGER = "manager"

MANAGER_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR)

# How much history a scan shows before it stops being a scan and starts being
# a report. The full list is one tap away for anyone allowed to see it.
RECENT_HISTORY = 5

# A work order that is finished, in either sense: what "ya se hizo" means.
DONE_STATUSES = (WorkOrder.Status.TERMINADA, WorkOrder.Status.VERIFICADA)


def scan_audience(user, asset) -> str:
    """Which of the four views this person gets. Deny by default."""
    if not user.is_authenticated:
        return PLATE
    # Deliberately NOT `user.is_platform_admin or ...`, the shortcut every
    # other permission check in this codebase takes. A platform admin has no
    # company, so the tenant contextvar is unset and every scoped read below
    # would quietly return nothing — an operational screen rendered blank and
    # wrong. Platform admins get the plate and read the record through the
    # ordinary equipment screens, where the bypass is explicit.
    if user.company_id is None or user.company_id != asset.company_id:
        return PLATE
    if user.role in MANAGER_ROLES:
        return MANAGER
    if user.role == User.Role.TECHNICIAN:
        return TECHNICIAN
    if user.role == User.Role.STAFF:
        return STAFF
    # A user invited without a role yet (brief 01 leaves `role` blank-able).
    # No role means no view, not "the smallest one" — the plate is what a
    # stranger gets, and that is the right answer for an account that has not
    # been given a job yet.
    return PLATE


# --- Per-audience reads ------------------------------------------------------
#
# Every queryset below goes through the *scoped* manager on purpose: by the
# time any of these run, `scan_audience` has already established that the
# viewer belongs to the asset's company, so the request contextvar is set to
# exactly that company. Tenant isolation is therefore enforced twice — once
# by the audience check, once by the manager — rather than talked about.


def _open_work_orders(asset):
    return (
        WorkOrder.objects.select_related("assigned_to")
        .filter(asset=asset, status__in=WorkOrder.OPEN_STATUSES)
        .order_by(F("due_date").asc(nulls_last=True), "-id")
    )


def _recent_history(asset):
    """The last few interventions that actually happened, newest first."""
    return (
        WorkOrder.objects.select_related("assigned_to", "completed_by")
        .filter(asset=asset, status__in=DONE_STATUSES)
        .order_by(F("finished_at").desc(nulls_last=True), "-id")[:RECENT_HISTORY]
    )


def technician_context(asset, user) -> dict:
    """Their own open work orders on this machine — and nothing else.

    Not "all open work orders, mine highlighted": the technician scanned this
    machine because they are about to work on it, and the answer to "what am
    I here to do?" must not require reading past four rows assigned to
    somebody else.
    """
    mine = workorder_services.annotate_overdue(
        _open_work_orders(asset).filter(assigned_to=user)
    )
    return {"my_work_orders": mine, "overdue_count": sum(1 for wo in mine if wo.overdue)}


def manager_context(asset) -> dict:
    """The supervisor's answer to "how is this machine doing?"."""
    open_work_orders = workorder_services.annotate_overdue(_open_work_orders(asset))
    plans = maintenance_services.annotate_due_state(
        asset.maintenance_plans.select_related("asset").filter(is_active=True)
    )
    return {
        "open_work_orders": open_work_orders,
        "overdue_count": sum(1 for wo in open_work_orders if wo.overdue),
        "plans": plans,
        "overdue_plans": [plan for plan in plans if plan.due_state == "vencido"],
        "history": _recent_history(asset),
    }


def staff_context(asset) -> dict:
    """Consultation only: the record and what has been done to it."""
    return {"history": _recent_history(asset)}


def scan_context(asset, audience: str, user) -> dict:
    """The one place that maps an audience to the data it may read."""
    if audience == TECHNICIAN:
        return technician_context(asset, user)
    if audience == MANAGER:
        return manager_context(asset)
    if audience == STAFF:
        return staff_context(asset)
    return {}
