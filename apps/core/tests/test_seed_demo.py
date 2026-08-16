"""What the demo seeds promise: fictional, idempotent, and worth showing.

Three of these are guards rather than feature tests, because each of the three
ways this command can go wrong is silent. A seed that duplicates on the second
run looks fine until somebody counts. A seed that carries a real customer's
name looks fine until it is on GitHub. A seed that runs against production
looks fine until it cannot be undone.
"""

import ast
import re

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import F
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Company, Site, Subscription, User
from apps.assets.models import Asset, AssetCategory
from apps.audit.models import AuditLog
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem
from apps.core import demo_data
from apps.core.management.commands import seed_demo as seed_module
from apps.kpis import periods, queries
from apps.maintenance.models import MaintenancePlan, MeterReading
from apps.maintenance.services import generate_for_company
from apps.requests_.models import MaintenanceRequest
from apps.workorders.models import WorkOrder, WorkOrderChecklistItem

# Every table the command writes to. Read through `.unscoped()` where the model
# is tenant-scoped, because these counts are taken outside a request and the
# scoped manager would answer zero for all of them (apps/core/tenancy.py).
SEEDED_MODELS = (
    Company,
    Subscription,
    Site,
    User,
    AssetCategory,
    Asset,
    ChecklistTemplate,
    ChecklistTemplateItem,
    MaintenancePlan,
    MeterReading,
    WorkOrder,
    WorkOrderChecklistItem,
    MaintenanceRequest,
)


def row_counts() -> dict[str, int]:
    return {
        model.__name__: (
            model.objects.unscoped().count()
            if hasattr(model.objects, "unscoped")
            else model.objects.count()
        )
        for model in SEEDED_MODELS
    }


class SeedDemoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.report = seed_module.seed_demo()
        cls.company = Company.objects.get(nit=demo_data.COMPANY_NIT)

    def work_orders(self):
        return WorkOrder.objects.unscoped().filter(company=self.company)

    def test_it_builds_the_whole_company_in_one_command(self):
        assert self.company.name == demo_data.COMPANY_NAME
        assert self.company.subscription.status == "active"
        assert Site.objects.unscoped().filter(company=self.company).count() == len(
            demo_data.SITES
        )
        assert User.objects.filter(company=self.company).count() == len(demo_data.USERS)
        assert Asset.objects.unscoped().filter(company=self.company).count() == len(
            demo_data.ASSETS
        )
        assert ChecklistTemplate.objects.unscoped().filter(
            company=self.company
        ).count() == len(demo_data.CHECKLISTS)
        assert MaintenancePlan.objects.unscoped().filter(
            company=self.company
        ).count() == len(demo_data.PLANS)

    def test_the_four_roles_are_there_and_each_password_works(self):
        roles = set(
            User.objects.filter(company=self.company).values_list("role", flat=True)
        )
        assert roles == {"admin", "supervisor", "technician", "staff"}

        for username, _role, password in self.report.passwords:
            user = User.objects.get(username=username)
            assert user.check_password(password), f"{username} no puede entrar"

    def test_running_it_twice_changes_no_counts(self):
        """CLAUDE.md rule 5, applied to the seeds: converge, never duplicate.

        The passwords are the one thing that does change on a re-run — they are
        generated with `secrets` and shown once, so a second run is also how
        somebody who lost the console output gets back in.
        """
        before = row_counts()
        first_passwords = {name: word for name, _role, word in self.report.passwords}

        second = seed_module.seed_demo()

        assert row_counts() == before
        second_passwords = {name: word for name, _role, word in second.passwords}
        assert second_passwords.keys() == first_passwords.keys()
        assert all(
            second_passwords[name] != first_passwords[name] for name in first_passwords
        )

    def test_the_scheduler_finds_nothing_left_to_do_right_after_seeding(self):
        """The plans are left pointing past the seeded horizon.

        Otherwise the first `generate_work_orders` of the demo would spray
        catch-up work orders across the screen — the scheduler working
        correctly, and a terrible first impression.
        """
        before = self.work_orders().count()

        result = generate_for_company(self.company, horizon_days=demo_data.HORIZON_DAYS)

        assert result.created == 0
        assert self.work_orders().count() == before

    def test_the_history_is_ninety_days_of_finished_work(self):
        anchor = timezone.localtime(self.company.created_at).date()
        verified = self.work_orders().filter(status=WorkOrder.Status.VERIFICADA)

        assert verified.count() > 20
        oldest = verified.order_by("due_date").first()
        assert (anchor - oldest.due_date).days >= demo_data.HISTORY_DAYS - 7
        # CLAUDE.md rule 3 holds in the seeded history too: nobody in it
        # verified their own work.
        assert not verified.filter(completed_by=F("verified_by")).exists()

    def test_every_closed_work_order_carries_evidence(self):
        for work_order in self.work_orders().filter(status=WorkOrder.Status.VERIFICADA):
            assert work_order.completed_by_id is not None
            assert work_order.verified_by_id is not None
            assert work_order.finished_at is not None
            assert work_order.work_done

    def test_the_checklists_of_finished_work_are_answered(self):
        unanswered = WorkOrderChecklistItem.objects.unscoped().filter(
            company=self.company,
            work_order__status=WorkOrder.Status.VERIFICADA,
            required=True,
            result="",
        )
        # A text item's answer is its note and it carries no `result`;
        # everything else must have one.
        assert not unanswered.exclude(item_type="text").exists()

    def test_the_dashboard_shows_numbers_with_something_behind_them(self):
        """The demo dashboard must not read «—» on every tile."""
        period = periods.resolve(None)
        today = timezone.localdate()

        compliance = queries.pm_compliance(self.company.pk, period)
        mtbf = queries.mtbf(self.company.pk, period)
        mttr = queries.mttr(self.company.pk, period)
        cost = queries.cost_by_asset_month(self.company.pk, period)
        backlog = queries.backlog(self.company.pk, today)

        assert compliance.scheduled > 0
        assert 60 <= compliance.percent <= 95, f"cumplimiento {compliance.percent} %"
        assert mtbf.hours is not None and mtbf.failures > 0
        assert mttr.hours is not None and mttr.repairs > 0
        assert cost.total_cop > 0
        assert backlog.total > 0

    def test_the_backlog_has_work_orders_of_every_age(self):
        """A backlog where every row is three days old teaches nobody what the
        ageing buckets are for."""
        backlog = queries.backlog(self.company.pk, timezone.localdate())

        assert backlog.under_7 > 0
        assert backlog.from_7_to_30 > 0
        assert backlog.over_30 > 0

    def test_the_hour_meter_climbs_and_the_plan_is_ready_to_fire(self):
        plan = MaintenancePlan.objects.unscoped().get(
            company=self.company, frequency_type=MaintenancePlan.FrequencyType.METER
        )
        readings = list(
            MeterReading.objects.unscoped()
            .filter(company=self.company)
            .order_by("read_at")
            .values_list("reading_hours", flat=True)
        )

        assert len(readings) >= 10
        assert readings == sorted(readings)
        # Under one interval away, so the demo can make the scheduler produce a
        # work order by entering a single reading.
        gap = readings[-1] - plan.hours_at_last_generated_wo
        assert 0 < gap < plan.meter_interval_hours

    def test_the_queue_of_failure_reports_is_not_empty(self):
        pending = MaintenanceRequest.objects.unscoped().filter(
            company=self.company, status=MaintenanceRequest.Status.NUEVA
        )

        assert pending.count() == len(demo_data.REQUESTS)

    def test_it_writes_no_audit_rows(self):
        """The audit log records what people did, and nobody did this.

        It is also the one table that could not be seeded idempotently: audit
        rows are immutable, so a second run could only append.
        """
        assert not AuditLog.objects.unscoped().filter(company=self.company).exists()


class ProductionGuardTests(TestCase):
    """A demo company inside a customer's database cannot be undone — verified
    work orders and audit rows are immutable by design. So the command asks."""

    @override_settings(DEBUG=False)
    def test_it_refuses_to_run_with_debug_off(self):
        with self.assertRaises(CommandError) as refusal:
            call_command("seed_demo")

        assert "--force" in str(refusal.exception)
        assert not Company.objects.filter(nit=demo_data.COMPANY_NIT).exists()

    @override_settings(DEBUG=False)
    def test_force_is_the_way_through(self):
        call_command("seed_demo", "--force", verbosity=0)

        assert Company.objects.filter(nit=demo_data.COMPANY_NIT).exists()


class FictionalDataTests(TestCase):
    """CLAUDE.md: personal data of Colombian customers falls under Ley 1581 —
    never copy real customer data into seeds, fixtures or the public repo.

    The catalogue is read as text rather than as imported objects: the rule is
    about what is written in the file, and a value assembled at runtime would
    slip past a check that only looked at `demo_data.USERS`.
    """

    # Domains a real person's address would carry. `example.com` is reserved by
    # RFC 2606 precisely so it can never be anybody's real inbox, and it is the
    # only domain these seeds are allowed to use. Add a customer's company
    # name, NIT or domain to this tuple the day the product has one — this list
    # is the guard, and an empty one would guard nothing.
    FORBIDDEN = (
        "@gmail.com",
        "@hotmail.com",
        "@outlook.com",
        "@yahoo.com",
        "@icloud.com",
    )

    def source_text(self) -> str:
        with open(demo_data.__file__, encoding="utf-8") as handle:
            return handle.read()

    def test_the_catalogue_carries_no_real_looking_address(self):
        text = self.source_text().lower()

        for domain in self.FORBIDDEN:
            assert domain not in text, f"dominio real en los seeds: {domain}"

    def test_every_address_in_the_seeds_is_a_reserved_one(self):
        addresses = re.findall(r"[\w.+-]+@[\w.-]+", self.source_text())

        assert addresses, "el catálogo debería traer direcciones de ejemplo"
        for address in addresses:
            assert address.endswith("@example.com"), address

    def test_no_credential_is_written_down(self):
        """Passwords are generated per run with `secrets` and printed once.

        A password in the repository is a password in every clone of it, and
        this repository is public. Asserted against the parsed syntax tree, not
        against the raw text: the module *talks* about passwords in its own
        comments, and a substring check that fails on a comment is a check
        somebody eventually deletes. What must not exist is a field or a
        variable that holds one.

        That the generated passwords actually differ between runs is asserted
        by `test_running_it_twice_changes_no_counts`.
        """
        tree = ast.parse(self.source_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names |= {
                    target.id.lower()
                    for target in node.targets
                    if isinstance(target, ast.Name)
                }
            elif isinstance(node, ast.Dict):
                names |= {
                    key.value.lower()
                    for key in node.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }

        offenders = [
            name
            for name in names
            for hint in ("password", "passwd", "clave", "secret", "token")
            if hint in name
        ]
        assert not offenders, offenders
