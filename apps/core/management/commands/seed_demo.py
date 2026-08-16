"""`manage.py seed_demo` — one command, one believable company.

What this exists for: a product whose dashboard reads «—» and whose backlog is
empty demonstrates nothing. This command writes ninety days of a plant's life —
work orders closed on time and late, breakdowns with downtime and cost, an hour
meter that climbs, a backlog of different ages — so the screens have something
to say the first time anybody opens them.

Three rules shape the implementation:

1. **It never runs against production by accident.** With `DEBUG=False` the
   command refuses and exits non-zero unless `--force` is passed explicitly.
   A demo company inside a customer's database is not a mistake you can undo:
   verified work orders and audit rows are, by design, undeletable.
2. **It is idempotent, the same way the scheduler is** (CLAUDE.md rule 5):
   every row is written with `get_or_create` against a natural key, so a second
   run finds what the first one wrote instead of duplicating it. Nothing is
   deleted and nothing already written is mutated — a row that exists is left
   exactly as it is.
3. **All data is fictional.** Every literal lives in `apps/core/demo_data.py`,
   which is checked by a test that reads it as text. Passwords are *not* in
   there: they are generated per run with `secrets` and printed once to the
   console. A password in the repository is a password in every clone of it.

Two things this command deliberately does not do:

- **It writes no audit rows.** The audit log records what people did, and
  nobody did this. Seeding it would also be the one thing here that cannot be
  made idempotent — audit rows are immutable, so a second run could only add
  more. The screen fills up as soon as the demo touches anything.
- **It writes no files.** No photos, no manuals: uploads live outside the
  database, so they would survive a rollback and pile up on re-runs.

The history is anchored to the demo company's own creation date, not to
"today". That is what makes re-running the command a week later a no-op instead
of a second, shifted copy of the same ninety days.
"""

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Company, Site, Subscription, User
from apps.assets.models import Asset, AssetCategory
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem
from apps.core import demo_data
from apps.core.tenancy import current_company_id
from apps.maintenance.models import MaintenancePlan, MeterReading
from apps.maintenance.services import WORK_ORDER_TYPE_BY_PLAN_KIND, advance_due_date
from apps.requests_.models import MaintenanceRequest
from apps.workorders import services as workorder_services
from apps.workorders.models import WorkOrder, WorkOrderChecklistItem

# When, in the plant's day, a scheduled job is closed. Any fixed hour would do;
# what matters is that it is a *local* hour, because PM compliance compares
# `finished_at` against `due_date` in Bogotá (apps/kpis/queries.py).
CLOSED_AT = time(15, 30)
CREATED_AT = time(5, 5)
VERIFIED_AT = time(9, 15)


@dataclass
class SeedReport:
    """What the run did, for the summary the command prints."""

    created: dict[str, int] = field(default_factory=dict)
    reused: dict[str, int] = field(default_factory=dict)
    passwords: list[tuple[str, str, str]] = field(default_factory=list)

    def count(self, kind: str, *, created: bool) -> None:
        bucket = self.created if created else self.reused
        bucket[kind] = bucket.get(kind, 0) + 1

    @property
    def anything_created(self) -> bool:
        return any(self.created.values())


def _aware(day: date, at: time) -> datetime:
    """A plant-local timestamp. `TIME_ZONE` is America/Bogota (CLAUDE.md)."""
    return timezone.make_aware(datetime.combine(day, at))


class DemoSeeder:
    """Writes the demo company. One instance per run; holds no global state."""

    def __init__(self, report: SeedReport):
        self.report = report
        self.company: Company | None = None
        self.anchor: date | None = None
        self.sites: dict[str, Site] = {}
        self.users: dict[str, User] = {}
        self.categories: dict[str, AssetCategory] = {}
        self.assets: dict[str, Asset] = {}
        self.checklists: dict[str, ChecklistTemplate] = {}
        self.plans: dict[str, MaintenancePlan] = {}

    # --- Helpers ------------------------------------------------------------

    def _track(self, kind: str, pair):
        instance, created = pair
        self.report.count(kind, created=created)
        return instance

    # --- The company --------------------------------------------------------

    def seed_company(self) -> None:
        """Company and subscription — the two tables that are not tenant-scoped.

        Deliberately the only thing written before the tenant contextvar is
        set: every other model here uses `CompanyScopedManager`, whose reads
        return *nothing* while that variable is unset (apps/core/tenancy.py).
        A `get_or_create` in that state never finds the existing row and
        creates a second one on every run — the silent kind of non-idempotency
        that only shows up as a duplicate three demos later.
        """
        self.company = self._track(
            "empresa",
            Company.objects.get_or_create(
                nit=demo_data.COMPANY_NIT,
                defaults={"name": demo_data.COMPANY_NAME, "is_active": True},
            ),
        )
        # The anchor is the company's own creation timestamp, so every date
        # below is a fixed offset from a value that never changes again. Run
        # the command today and again in a month and the second run computes
        # exactly the same due dates — which is what makes `get_or_create`
        # find them instead of writing a shifted second history.
        self.anchor = timezone.localtime(self.company.created_at).date()

        self._track(
            "suscripción",
            Subscription.objects.get_or_create(
                company=self.company,
                defaults={
                    "plan": demo_data.SUBSCRIPTION["plan"],
                    "status": demo_data.SUBSCRIPTION["status"],
                    "max_users": demo_data.SUBSCRIPTION["max_users"],
                    "max_assets": demo_data.SUBSCRIPTION["max_assets"],
                    "current_period_end": self.anchor
                    + timedelta(days=demo_data.SUBSCRIPTION["period_days"]),
                },
            ),
        )

    def seed_sites(self) -> None:
        for spec in demo_data.SITES:
            self.sites[spec["name"]] = self._track(
                "sede",
                Site.objects.get_or_create(
                    company=self.company,
                    name=spec["name"],
                    defaults={"address": spec["address"]},
                ),
            )

    def seed_users(self) -> None:
        for spec in demo_data.USERS:
            user, created = User.objects.get_or_create(
                username=spec["username"],
                defaults={
                    "company": self.company,
                    "role": spec["role"],
                    "first_name": spec["first_name"],
                    "last_name": spec["last_name"],
                    "email": spec["email"],
                    "whatsapp_phone": spec["whatsapp_phone"],
                },
            )
            if user.company_id != self.company.pk:
                # Usernames are unique across the whole platform. Adopting a
                # user that belongs to somebody else — and handing out a fresh
                # password for their account below — is the worst thing this
                # command could do, so it stops instead.
                raise CommandError(
                    f"El usuario «{user.get_username()}» ya existe y pertenece a otra "
                    "empresa. Renombra ese usuario o cambia los nombres en "
                    "apps/core/demo_data.py antes de sembrar la demo."
                )
            self.report.count("usuario", created=created)
            # The password is reset on every run, including runs that created
            # nothing: it is never stored anywhere legible, so the only way to
            # get back into the demo after losing the console output is to run
            # the command again.
            password = secrets.token_urlsafe(9)
            user.set_password(password)
            user.save(update_fields=["password"])
            self.report.passwords.append(
                (user.get_username(), user.get_role_display(), password)
            )
            self.users[spec["username"]] = user

    # --- Equipment ----------------------------------------------------------

    def seed_assets(self) -> None:
        for name in demo_data.CATEGORIES:
            self.categories[name] = self._track(
                "categoría",
                AssetCategory.objects.get_or_create(company=self.company, name=name),
            )

        creator = self.users[demo_data.ADMIN]
        for spec in demo_data.ASSETS:
            self.assets[spec["code"]] = self._track(
                "equipo",
                Asset.objects.get_or_create(
                    company=self.company,
                    code=spec["code"],
                    defaults={
                        "site": self.sites[spec["site"]],
                        "category": self.categories[spec["category"]],
                        "name": spec["name"],
                        "brand": spec["brand"],
                        "model": spec["model"],
                        "serial_number": spec["serial_number"],
                        "criticality": spec["criticality"],
                        "status": spec["status"],
                        "location_detail": spec["location_detail"],
                        "purchase_date": self.anchor
                        - timedelta(days=365 * spec["purchase_years_ago"]),
                        "specs": spec["specs"],
                        "baja_reason": spec.get("baja_reason", ""),
                        "created_by": creator,
                    },
                ),
            )

    # --- Checklists ---------------------------------------------------------

    def seed_checklists(self) -> None:
        """Templates written row by row rather than through `services.add_item`.

        `add_item` funnels through `get_editable_version`, which forks a
        template the moment a work order references it (CLAUDE.md rule 4). The
        seeds write history *onto* these templates, so a second run calling
        `add_item` would fork every one of them into a v2 nobody asked for.
        Writing the rows directly is what keeps re-running the command a no-op.
        """
        for spec in demo_data.CHECKLISTS:
            template = self._track(
                "checklist",
                ChecklistTemplate.objects.get_or_create(
                    company=self.company,
                    name=spec["name"],
                    version=1,
                    defaults={
                        "category": self.categories[spec["category"]],
                        "is_active": True,
                    },
                ),
            )
            self.checklists[spec["name"]] = template
            for order, item in enumerate(spec["items"], start=1):
                ChecklistTemplateItem.objects.get_or_create(
                    company=self.company,
                    template=template,
                    order=order,
                    defaults={
                        "text": item["text"],
                        "item_type": item["item_type"],
                        "unit": item.get("unit", ""),
                        "min_value": item.get("min_value"),
                        "max_value": item.get("max_value"),
                        "required": item.get("required", True),
                    },
                )

    # --- Plans --------------------------------------------------------------

    def seed_plans(self) -> None:
        technician = self.users[demo_data.TECHNICIAN]
        for spec in demo_data.PLANS:
            is_calendar = spec["frequency_type"] == MaintenancePlan.FrequencyType.CALENDAR
            defaults = {
                "kind": spec["kind"],
                "frequency_type": spec["frequency_type"],
                "checklist_template": (
                    self.checklists[spec["checklist"]] if spec["checklist"] else None
                ),
                "default_assignee": technician,
                "estimated_minutes": spec["estimated_minutes"],
                "is_active": True,
            }
            if is_calendar:
                defaults["interval_days"] = spec["interval_days"]
                # Overwritten at the end of `seed_history` with the first
                # occurrence past the horizon, so the scheduler has nothing
                # left to catch up on right after seeding.
                defaults["next_due_date"] = self.anchor
            else:
                defaults["meter_interval_hours"] = spec["meter_interval_hours"]

            self.plans[spec["name"]] = self._track(
                "plan",
                MaintenancePlan.objects.get_or_create(
                    company=self.company,
                    asset=self.assets[spec["asset"]],
                    name=spec["name"],
                    defaults=defaults,
                ),
            )

    # --- History ------------------------------------------------------------

    def _occurrences(self, spec: dict) -> tuple[list[date], date]:
        """Every due date of a calendar plan in the window, plus the next one.

        Stepped with `advance_due_date`, the same function the scheduler uses,
        so a "monthly" plan lands on the same day of each month here as it
        would in production instead of drifting by two days a quarter. The
        extra date returned alongside is what the plan's `next_due_date`
        becomes: the first occurrence the seeds do *not* write, so running
        `generate_work_orders` right after seeding creates nothing.
        """
        due = self.anchor - timedelta(days=demo_data.HISTORY_DAYS)
        limit = self.anchor + timedelta(days=demo_data.HORIZON_DAYS)
        dates: list[date] = []
        while due <= limit:
            dates.append(due)
            due = advance_due_date(due, spec["interval_days"])
        return dates, due

    @staticmethod
    def _forgotten_date(dates: list[date], anchor: date, days_ago: int | None):
        """Which occurrence is left open, so the backlog has an age.

        The one closest to `days_ago` days before the anchor, and only among
        the ones already overdue — an occurrence in the future is not backlog,
        it is next week's work.
        """
        if days_ago is None:
            return None
        overdue = [day for day in dates if day < anchor]
        if not overdue:
            return None
        return min(overdue, key=lambda day: abs((anchor - day).days - days_ago))

    def _answer_items(self, work_order: WorkOrder, *, with_failure: bool) -> None:
        """Fill the snapshot the way a technician would have on the day.

        `with_failure` is what puts a red row in some of the history: a plant
        where every checklist reads OK for ninety days is not a plant, and the
        work-order report is more convincing when it has something to report.
        """
        items = list(workorder_services.checklist_items(work_order))
        if not items:
            return
        failing_order = items[2].order if with_failure and len(items) > 2 else None
        for item in items:
            fails = item.order == failing_order
            if item.item_type == WorkOrderChecklistItem.ItemType.TEXT:
                item.result = ""
                item.numeric_value = None
                item.note = (
                    "Se deja seguimiento para la próxima rutina."
                    if with_failure
                    else "Sin novedad."
                )
            elif item.item_type == WorkOrderChecklistItem.ItemType.NUMERIC:
                low, high = item.min_value, item.max_value
                middle = (low + high) / 2
                # Out of range IS the failure — the same arithmetic
                # `services._resolve_numeric` applies when a technician types
                # the number, reproduced here because these rows are written
                # directly rather than through the HTMX save.
                item.numeric_value = (high + Decimal("1.50")) if fails else middle
                item.result = (
                    WorkOrderChecklistItem.Result.FALLA
                    if fails
                    else WorkOrderChecklistItem.Result.OK
                )
                item.note = "Fuera de rango, se reporta." if fails else ""
            else:
                item.result = (
                    WorkOrderChecklistItem.Result.FALLA
                    if fails
                    else WorkOrderChecklistItem.Result.OK
                )
                item.numeric_value = None
                item.note = "Se ajusta en la próxima parada." if fails else ""
        WorkOrderChecklistItem.objects.bulk_update(
            items, ["result", "numeric_value", "note"]
        )

    def _close_and_seal(
        self,
        work_order: WorkOrder,
        *,
        started_at: datetime,
        finished_at: datetime,
        verified_at: datetime,
        work_done: str,
        downtime_minutes: int,
        labor_cost_cop: int,
        parts_cost_cop: int,
        with_failure: bool = False,
    ) -> None:
        """Write a finished, verified work order — in the order the seal allows.

        Not through `services.transition`: that stamps `timezone.now()`, and
        every timestamp here belongs to a day in the past. The invariants the
        state machine protects are still respected — `completed_by` is the
        technician, `verified_by` is the supervisor, and they are different
        people (CLAUDE.md rule 3).

        The order matters and is the same one `apps/reports/tests/factories.py`
        follows: children first, seal last. A `verificada` work order refuses
        every write to its own row, its checklist items and its photos.
        """
        self._answer_items(work_order, with_failure=with_failure)

        work_order.assigned_to = self.users[demo_data.TECHNICIAN]
        work_order.completed_by = self.users[demo_data.TECHNICIAN]
        work_order.started_at = started_at
        work_order.finished_at = finished_at
        work_order.work_done = work_done
        work_order.downtime_minutes = downtime_minutes
        work_order.labor_cost_cop = labor_cost_cop
        work_order.parts_cost_cop = parts_cost_cop
        work_order.status = WorkOrder.Status.TERMINADA
        work_order.save()

        work_order.verified_by = self.users[demo_data.SUPERVISOR]
        work_order.verified_at = verified_at
        work_order.status = WorkOrder.Status.VERIFICADA
        work_order.save()

    def _backdate(self, work_order: WorkOrder, due: date) -> None:
        """`created_at` is `auto_now_add`, so it can only be set afterwards.

        Left alone, a work order from ninety days ago would tell the detail
        screen's timeline it was created this morning. Capped at the anchor,
        because a work order scheduled for next Tuesday was still created
        today — the scheduler writes it in advance, it does not time-travel.
        Done before the row is sealed: a verified work order refuses this write
        too, and rightly so.
        """
        WorkOrder.objects.filter(pk=work_order.pk).update(
            created_at=_aware(min(due, self.anchor), CREATED_AT)
        )

    def seed_calendar_history(self) -> None:
        for spec in demo_data.PLANS:
            if spec["frequency_type"] != MaintenancePlan.FrequencyType.CALENDAR:
                continue
            plan = self.plans[spec["name"]]
            template = plan.checklist_template
            dates, next_due = self._occurrences(spec)
            forgotten = self._forgotten_date(
                dates, self.anchor, spec["forgotten_days_ago"]
            )

            for index, due in enumerate(dates):
                work_order, created = WorkOrder.objects.get_or_create(
                    plan=plan,
                    due_date=due,
                    defaults={
                        "company_id": self.company.pk,
                        "asset_id": plan.asset_id,
                        # The same mapping the scheduler applies, imported
                        # rather than repeated: a lubrication plan produces a
                        # preventive work order, an inspection plan an
                        # inspection, and the KPI that measures the preventive
                        # plan counts only the former.
                        "type": WORK_ORDER_TYPE_BY_PLAN_KIND.get(
                            spec["kind"], WorkOrder.Type.PREVENTIVO
                        ),
                        "origin": WorkOrder.Origin.PLAN,
                        "status": WorkOrder.Status.ASIGNADA,
                        "assigned_to": self.users[demo_data.TECHNICIAN],
                    },
                )
                self.report.count("OT preventiva", created=created)
                if not created:
                    # Second run: the row is already there, possibly sealed.
                    # Touching it is exactly what idempotency forbids.
                    continue

                workorder_services.snapshot_checklist(work_order, template)
                self._backdate(work_order, due)

                still_open = due >= self.anchor or due == forgotten
                if still_open:
                    continue

                late = index % demo_data.LATE_EVERY == demo_data.LATE_EVERY - 1
                closed_on = due + timedelta(days=demo_data.LATE_BY_DAYS if late else 0)
                finished_at = _aware(closed_on, CLOSED_AT)
                self._close_and_seal(
                    work_order,
                    started_at=finished_at
                    - timedelta(minutes=spec["estimated_minutes"]),
                    finished_at=finished_at,
                    verified_at=_aware(closed_on + timedelta(days=1), VERIFIED_AT),
                    work_done=demo_data.PREVENTIVE_WORK_DONE[
                        index % len(demo_data.PREVENTIVE_WORK_DONE)
                    ],
                    downtime_minutes=demo_data.PREVENTIVE_DOWNTIME_MINUTES[
                        index % len(demo_data.PREVENTIVE_DOWNTIME_MINUTES)
                    ],
                    labor_cost_cop=demo_data.PREVENTIVE_LABOR_COP[
                        index % len(demo_data.PREVENTIVE_LABOR_COP)
                    ],
                    parts_cost_cop=demo_data.PREVENTIVE_PARTS_COP[
                        index % len(demo_data.PREVENTIVE_PARTS_COP)
                    ],
                    with_failure=index % 7 == 3,
                )

            if plan.next_due_date != next_due:
                plan.next_due_date = next_due
                plan.save(update_fields=["next_due_date", "updated_at"])

    def seed_corrective_history(self) -> None:
        for spec in demo_data.CORRECTIVE_WORK_ORDERS:
            asset = self.assets[spec["asset"]]
            day = self.anchor - timedelta(days=spec["days_ago"])
            work_order, created = WorkOrder.objects.get_or_create(
                company_id=self.company.pk,
                asset=asset,
                type=WorkOrder.Type.CORRECTIVO,
                due_date=day,
                defaults={
                    "origin": WorkOrder.Origin.MANUAL,
                    "status": WorkOrder.Status.ASIGNADA,
                    "priority": spec["priority"],
                    "assigned_to": self.users[demo_data.TECHNICIAN],
                    "failure_description": spec["failure_description"],
                },
            )
            self.report.count("OT correctiva", created=created)
            if not created:
                continue
            self._backdate(work_order, day)
            finished_at = _aware(day, CLOSED_AT)
            self._close_and_seal(
                work_order,
                # MTTR is the average of (finished_at − started_at) over
                # corrective work orders, so this span is the number the
                # dashboard reports as «cuánto tardamos en repararlo».
                started_at=finished_at - timedelta(hours=spec["repair_hours"]),
                finished_at=finished_at,
                verified_at=_aware(day + timedelta(days=1), VERIFIED_AT),
                work_done=spec["work_done"],
                downtime_minutes=spec["downtime_minutes"],
                labor_cost_cop=spec["labor_cost_cop"],
                parts_cost_cop=spec["parts_cost_cop"],
            )

    def seed_meter(self) -> None:
        """The compressor's hour meter, and the two routines it triggered."""
        plan = next(
            plan
            for name, plan in self.plans.items()
            if plan.frequency_type == MaintenancePlan.FrequencyType.METER
        )
        asset = self.assets["CMP-01"]

        hours_by_days_ago: dict[int, Decimal] = {}
        days_ago = demo_data.HISTORY_DAYS
        while days_ago >= 0:
            elapsed = Decimal(demo_data.HISTORY_DAYS - days_ago)
            hours = demo_data.METER_START_HOURS + elapsed * demo_data.METER_HOURS_PER_DAY
            hours_by_days_ago[days_ago] = hours
            read_at = _aware(self.anchor - timedelta(days=days_ago), CLOSED_AT)
            self._track(
                "lectura de horómetro",
                MeterReading.objects.get_or_create(
                    company_id=self.company.pk,
                    asset=asset,
                    read_at=read_at,
                    defaults={
                        "reading_hours": hours,
                        "source": MeterReading.Source.MANUAL,
                        "recorded_by": self.users[demo_data.TECHNICIAN],
                    },
                ),
            )
            days_ago -= demo_data.METER_READING_EVERY_DAYS

        def hours_at(target_days_ago: int) -> Decimal:
            closest = min(hours_by_days_ago, key=lambda d: abs(d - target_days_ago))
            return hours_by_days_ago[closest]

        baseline = plan.hours_at_last_generated_wo
        for spec in demo_data.METER_WORK_ORDERS:
            day = self.anchor - timedelta(days=spec["days_ago"])
            work_order, created = WorkOrder.objects.get_or_create(
                plan=plan,
                due_date=day,
                defaults={
                    "company_id": self.company.pk,
                    "asset_id": asset.pk,
                    "type": WorkOrder.Type.PREVENTIVO,
                    "origin": WorkOrder.Origin.PLAN,
                    "status": WorkOrder.Status.ASIGNADA,
                    "assigned_to": self.users[demo_data.TECHNICIAN],
                },
            )
            self.report.count("OT preventiva", created=created)
            baseline = hours_at(spec["days_ago"])
            if not created:
                continue
            workorder_services.snapshot_checklist(work_order, plan.checklist_template)
            self._backdate(work_order, day)
            finished_at = _aware(day, CLOSED_AT)
            self._close_and_seal(
                work_order,
                started_at=finished_at - timedelta(minutes=120),
                finished_at=finished_at,
                verified_at=_aware(day + timedelta(days=1), VERIFIED_AT),
                work_done=spec["work_done"],
                downtime_minutes=90,
                labor_cost_cop=140_000,
                parts_cost_cop=95_000,
            )

        # The meter plan is now "already served up to that reading": the newest
        # reading sits below baseline + 250 h, so the scheduler creates nothing
        # until somebody enters the next one — which is exactly the moment the
        # demo script uses to show a work order appearing by itself.
        if plan.hours_at_last_generated_wo != baseline:
            plan.hours_at_last_generated_wo = baseline
            plan.save(update_fields=["hours_at_last_generated_wo", "updated_at"])

    def seed_requests(self) -> None:
        for spec in demo_data.REQUESTS:
            day = self.anchor - timedelta(days=spec["days_ago"])
            request_obj, created = MaintenanceRequest.objects.get_or_create(
                company_id=self.company.pk,
                asset=self.assets[spec["asset"]],
                description=spec["description"],
                defaults={
                    "reported_by": self.users[spec["reporter"]],
                    "status": MaintenanceRequest.Status.NUEVA,
                },
            )
            self.report.count("solicitud", created=created)
            if created:
                # `created_at` is auto_now_add here too, and «hace 2 días» is
                # part of what makes the queue look like a queue.
                MaintenanceRequest.objects.filter(pk=request_obj.pk).update(
                    created_at=_aware(day, CLOSED_AT)
                )

    # --- Entry point --------------------------------------------------------

    def run(self) -> SeedReport:
        self.seed_company()
        # Every read and write below goes through the scoped managers bound to
        # this company — the same guarantee the request middleware gives a
        # view, reproduced for a context that has no middleware (the shape
        # `maintenance.services.generate_for_company` uses).
        token = current_company_id.set(self.company.pk)
        try:
            self.seed_sites()
            self.seed_users()
            self.seed_assets()
            self.seed_checklists()
            self.seed_plans()
            self.seed_calendar_history()
            self.seed_corrective_history()
            self.seed_meter()
            self.seed_requests()
        finally:
            current_company_id.reset(token)
        return self.report


def seed_demo() -> SeedReport:
    """Write the demo company and return what happened. Used by the tests."""
    with transaction.atomic():
        return DemoSeeder(SeedReport()).run()


class Command(BaseCommand):
    help = (
        "Creates the fictional demo company (Empaques La Sabana S.A.S.) with "
        "90 days of maintenance history. Idempotent: running it twice changes "
        "nothing. Refuses to run with DEBUG=False unless --force is given."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Run even with DEBUG=False. Only for a staging or demo "
                "deployment — never against a customer's database."
            ),
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "DEBUG=False: esto parece un entorno de producción y los datos "
                "de demostración no se pueden borrar después (las OTs "
                "verificadas y la auditoría son inmutables por diseño). Si de "
                "verdad quieres sembrar la demo aquí, repite el comando con "
                "--force."
            )

        report = seed_demo()

        self.stdout.write(self.style.SUCCESS(f"Empresa demo: {demo_data.COMPANY_NAME}"))
        self._write_counts("Creado", report.created)
        self._write_counts("Ya existía", report.reused)

        self.stdout.write("")
        self.stdout.write("Usuarios y contraseñas (se generan nuevas en cada corrida):")
        width = max(len(username) for username, _role, _password in report.passwords)
        for username, role, password in report.passwords:
            self.stdout.write(f"  {username:<{width}}  {role:<15}  {password}")
        self.stdout.write("")
        self.stdout.write(
            "Estas contraseñas solo se muestran aquí. Vuelve a correr el comando "
            "si las pierdes."
        )
        if not report.anything_created:
            self.stdout.write(
                self.style.WARNING(
                    "No se creó nada nuevo: la demo ya estaba sembrada. Solo se "
                    "renovaron las contraseñas."
                )
            )

    def _write_counts(self, label: str, counts: dict[str, int]) -> None:
        if not counts:
            return
        detail = " · ".join(f"{kind}: {total}" for kind, total in sorted(counts.items()))
        self.stdout.write(f"{label} — {detail}")
