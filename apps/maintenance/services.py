"""Preventive-plan scheduling: the rules that turn plans into work orders.

Three properties this module exists to guarantee, all of them CLAUDE.md
rules rather than nice-to-haves:

1. **Idempotency is structural, not procedural** (rule 5). Work orders are
   written with `get_or_create` against `UNIQUE(plan, due_date)`, so a
   second run — or a first run that crashed halfway and gets retried —
   converges on the same rows instead of duplicating them. No "have I
   already run today?" bookkeeping to get wrong.
2. **No drift.** A late calendar plan catches up from its *own* overdue due
   date, one interval at a time, so the missed work orders carry their real
   historical dates and the series never slips forward by however long the
   cron was down.
3. **Tenant isolation holds outside the request cycle** (rule 1). There is
   no middleware in a cron job, so `generate_for_company` sets the tenant
   contextvar itself, per company, and resets it before moving to the next
   one. Company A's iteration cannot see, let alone write, company B's rows.

Reads that must work with no tenant context at all (the newest meter
reading of an asset we already hold) go through `.objects.unscoped()` with
an explicit `asset_id=` filter, for the reason spelled out at the top of
apps/checklists/services.py: a `CompanyScopedManager` silently returns
nothing outside a request.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from apps.accounts.models import Company
from apps.assets.models import Asset
from apps.checklists.models import ChecklistTemplate
from apps.core.tenancy import current_company_id
from apps.maintenance.models import MaintenancePlan, MeterReading
from apps.workorders import services as workorder_services
from apps.workorders.models import WorkOrder

# Presets that mean a named calendar period rather than a literal day count.
# Advancing "monthly" by 30 days walks Jan 31 to Mar 2 and then keeps sliding;
# advancing it by one calendar month lands on Feb 28 and stays anchored to the
# end of the month (acceptance criterion 3).
MONTHS_BY_INTERVAL_DAYS: dict[int, int] = {30: 1, 90: 3, 180: 6, 365: 12}

# A calendar plan due within this many days is flagged "próximo a vencer" in
# the UI. Presentation only — the scheduler ignores it.
DUE_SOON_DAYS = 7

WORK_ORDER_TYPE_BY_PLAN_KIND = {
    MaintenancePlan.Kind.PREVENTIVO: WorkOrder.Type.PREVENTIVO,
    MaintenancePlan.Kind.INSPECCION: WorkOrder.Type.INSPECCION,
    MaintenancePlan.Kind.LUBRICACION: WorkOrder.Type.PREVENTIVO,
    MaintenancePlan.Kind.CALIBRACION: WorkOrder.Type.PREVENTIVO,
}


@dataclass
class SchedulerResult:
    """What one scheduler run did — the summary the command prints and,
    later (brief 08), the payload n8n forwards."""

    plans_evaluated: int = 0
    created: int = 0
    skipped_existing: int = 0

    def __add__(self, other: "SchedulerResult") -> "SchedulerResult":
        return SchedulerResult(
            plans_evaluated=self.plans_evaluated + other.plans_evaluated,
            created=self.created + other.created,
            skipped_existing=self.skipped_existing + other.skipped_existing,
        )

    def as_line(self) -> str:
        return (
            f"plans evaluated: {self.plans_evaluated} · "
            f"created: {self.created} · "
            f"skipped-existing: {self.skipped_existing}"
        )


# --- Date arithmetic --------------------------------------------------------


def add_months(due_date: date, months: int) -> date:
    """Add calendar months, clamping to the target month's last day.

    Jan 31 + 1 month -> Feb 28 (Feb 29 in a leap year). Note the standard
    consequence: from Feb 28 the next step is Mar 28, not Mar 31 — month-end
    anchoring is not sticky. That is the conventional behaviour and the one
    the brief asks for.
    """
    total = due_date.month - 1 + months
    year = due_date.year + total // 12
    month = total % 12 + 1
    day = min(due_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def advance_due_date(due_date: date, interval_days: int) -> date:
    """The one place that knows a 30-day preset means "monthly"."""
    months = MONTHS_BY_INTERVAL_DAYS.get(interval_days)
    if months is None:
        return due_date + timedelta(days=interval_days)
    return add_months(due_date, months)


# --- Meter readings ---------------------------------------------------------


def latest_reading_hours(asset_id: int) -> Decimal | None:
    """Newest hour-meter value for an asset, or None if it has no readings."""
    return MeterReading.objects.unscoped().filter(asset_id=asset_id).aggregate(
        models.Max("reading_hours")
    )["reading_hours__max"]


# --- Checklist resolution ---------------------------------------------------


def resolve_checklist_template(plan: MaintenancePlan) -> ChecklistTemplate | None:
    """The template version a work order created *now* would snapshot.

    A plan points at whichever version existed when it was written, but
    brief 03 forks a locked template into version n+1 and retires the
    parent. So the plan's stored FK is a pointer into a lineage, not the
    answer: walk the lineage forward and return its newest *active* version
    (None if the whole lineage has been deactivated).

    Brief 05 calls this when it copies the items into the work order's
    frozen checklist. Brief 04 stores nothing — the resolution is
    deliberately late, exactly as the brief specifies ("latest active
    version resolved at WO-creation time"), and the plan screens show the
    operator which version they will get.
    """
    template = plan.checklist_template
    if template is None:
        return None

    lineage = [template]
    current = template
    while True:
        child = (
            ChecklistTemplate.objects.unscoped()
            .filter(parent=current)
            .order_by("-version", "-pk")
            .first()
        )
        if child is None:
            break
        lineage.append(child)
        current = child

    active = [version for version in lineage if version.is_active]
    if not active:
        return None
    return max(active, key=lambda version: (version.version, version.pk))


# --- Scheduling -------------------------------------------------------------


def _create_work_order(plan: MaintenancePlan, *, due_date: date, result: SchedulerResult):
    work_order, created = WorkOrder.objects.get_or_create(
        plan=plan,
        due_date=due_date,
        defaults={
            "company_id": plan.company_id,
            "asset_id": plan.asset_id,
            "type": WORK_ORDER_TYPE_BY_PLAN_KIND.get(plan.kind, WorkOrder.Type.PREVENTIVO),
            "origin": WorkOrder.Origin.PLAN,
            # Status stays at the model default (`abierta`) even when the plan
            # names a default assignee: who may move a work order out of
            # `abierta` is brief 05's transition matrix, and this brief does
            # not get to pre-empt it.
            "assigned_to_id": plan.default_assignee_id,
        },
    )
    if created:
        # Brief 05, build item 2: the checklist is frozen onto the work order
        # the moment it is born. Only on `created` — a second scheduler run
        # returning the existing row must not append a second snapshot, which
        # is the same idempotency guarantee `get_or_create` gives the row
        # itself (CLAUDE.md rule 5), extended to its children.
        workorder_services.snapshot_checklist(work_order, resolve_checklist_template(plan))
        result.created += 1
    else:
        result.skipped_existing += 1
    return work_order


def _generate_calendar(
    plan: MaintenancePlan, *, today: date, horizon_days: int, result: SchedulerResult
) -> None:
    limit = today + timedelta(days=horizon_days)
    original_due_date = plan.next_due_date
    # Terminates because interval_days >= 1 is a database constraint: every
    # iteration strictly advances next_due_date, so the number of iterations
    # is bounded by (limit - next_due_date) in days.
    while plan.next_due_date is not None and plan.next_due_date <= limit:
        _create_work_order(plan, due_date=plan.next_due_date, result=result)
        plan.next_due_date = advance_due_date(plan.next_due_date, plan.interval_days)
    if plan.next_due_date != original_due_date:
        plan.save(update_fields=["next_due_date", "updated_at"])


def _generate_meter(plan: MaintenancePlan, *, today: date, result: SchedulerResult) -> None:
    latest = latest_reading_hours(plan.asset_id)
    if latest is None:
        return
    if latest - plan.hours_at_last_generated_wo < plan.meter_interval_hours:
        return
    # One work order per crossing, not one per elapsed interval: a machine
    # that jumped from 95 h to 210 h on a 100 h plan needs a single service,
    # not two. The baseline moves to the reading we acted on, so the next one
    # is due a full interval later (acceptance criterion 4).
    _create_work_order(plan, due_date=today, result=result)
    plan.hours_at_last_generated_wo = latest
    plan.save(update_fields=["hours_at_last_generated_wo", "updated_at"])


def _schedulable_plans():
    return (
        MaintenancePlan.objects.select_related("asset")
        .filter(is_active=True)
        .exclude(asset__status=Asset.Status.DADO_DE_BAJA)
        .order_by("pk")
    )


@transaction.atomic
def _generate_scoped(*, today: date, horizon_days: int) -> SchedulerResult:
    result = SchedulerResult()
    for plan in _schedulable_plans():
        result.plans_evaluated += 1
        if plan.is_calendar:
            _generate_calendar(plan, today=today, horizon_days=horizon_days, result=result)
        else:
            _generate_meter(plan, today=today, result=result)
    return result


def generate_for_company(
    company: Company, *, today: date | None = None, horizon_days: int = 0
) -> SchedulerResult:
    """Run the scheduler for exactly one company.

    Sets the tenant contextvar for the duration and resets it afterwards, so
    every read and write inside goes through the scoped manager bound to
    this company — the same guarantee the request middleware gives a view,
    reproduced for a context (cron) that has no middleware.
    """
    today = today or timezone.localdate()
    token = current_company_id.set(company.pk)
    try:
        return _generate_scoped(today=today, horizon_days=horizon_days)
    finally:
        current_company_id.reset(token)


def generate_work_orders(
    *, today: date | None = None, horizon_days: int = 0
) -> tuple[SchedulerResult, list[tuple[Company, SchedulerResult]]]:
    """Run the scheduler for every active company, one tenant at a time."""
    today = today or timezone.localdate()
    total = SchedulerResult()
    per_company: list[tuple[Company, SchedulerResult]] = []
    for company in Company.objects.filter(is_active=True).order_by("pk"):
        result = generate_for_company(company, today=today, horizon_days=horizon_days)
        per_company.append((company, result))
        total = total + result
    return total, per_company


# --- Presentation helpers ---------------------------------------------------

DUE_STATE_LABELS = {
    "inactivo": "Inactivo",
    "vencido": "Vencido",
    "por_vencer": "Próximo a vencer",
    "al_dia": "Al día",
    "sin_lecturas": "Sin lecturas",
}


def _calendar_due_state(plan: MaintenancePlan, *, today: date) -> str:
    if plan.next_due_date is None:
        return "al_dia"
    if plan.next_due_date < today:
        return "vencido"
    if (plan.next_due_date - today).days <= DUE_SOON_DAYS:
        return "por_vencer"
    return "al_dia"


def _meter_due_state(plan: MaintenancePlan, *, latest: Decimal | None) -> str:
    if latest is None:
        return "sin_lecturas"
    elapsed = latest - plan.hours_at_last_generated_wo
    if elapsed >= plan.meter_interval_hours:
        return "vencido"
    if elapsed >= plan.meter_interval_hours * Decimal("0.9"):
        return "por_vencer"
    return "al_dia"


def annotate_due_state(plans, *, today: date | None = None) -> list[MaintenancePlan]:
    """Attach `due_state` / `due_label` to each plan for the templates.

    Batched on purpose: the newest reading of every meter-tracked asset in
    the set is fetched in one aggregate query instead of one per row, so a
    plan list never turns into an N+1.
    """
    today = today or timezone.localdate()
    plans = list(plans)

    meter_asset_ids = {
        plan.asset_id for plan in plans if not plan.is_calendar and plan.is_active
    }
    latest_by_asset: dict[int, Decimal] = {}
    if meter_asset_ids:
        rows = (
            MeterReading.objects.unscoped()
            .filter(asset_id__in=meter_asset_ids)
            .values("asset_id")
            .annotate(latest=models.Max("reading_hours"))
        )
        latest_by_asset = {row["asset_id"]: row["latest"] for row in rows}

    for plan in plans:
        if not plan.is_active:
            state = "inactivo"
        elif plan.is_calendar:
            state = _calendar_due_state(plan, today=today)
        else:
            state = _meter_due_state(plan, latest=latest_by_asset.get(plan.asset_id))
        plan.due_state = state
        plan.due_label = DUE_STATE_LABELS[state]
    return plans
