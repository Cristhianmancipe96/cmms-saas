import pytest
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from apps.accounts.tests.factories import CompanyFactory
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem
from apps.checklists.tests.factories import (
    ChecklistTemplateFactory,
    ChecklistTemplateItemFactory,
    create_flowpac_inspeccion_semanal,
)
from apps.core.tenancy import current_company_id
from apps.workorders.tests.factories import lock_template


class ChecklistTemplateIsLockedTests(TestCase):
    """Brief 05 made the lock real: a template is locked once a work order
    has snapshotted it. These tests use actual work orders — a mocked
    `is_locked` proves nothing about the foreign key the real one reads.
    """

    def test_is_locked_is_false_without_work_orders(self):
        template = ChecklistTemplateFactory()

        assert template.is_locked() is False

    def test_is_locked_is_true_once_a_work_order_references_it(self):
        template = ChecklistTemplateFactory()
        lock_template(template)

        assert template.is_locked() is True

    def test_a_work_order_on_another_template_does_not_lock_this_one(self):
        template = ChecklistTemplateFactory()
        other = ChecklistTemplateFactory(company=template.company)
        lock_template(other)

        assert template.is_locked() is False

    def test_the_lock_holds_with_no_tenant_context_set(self):
        """The failure this guards against is a silent no-op, not an error.

        `self.work_orders.exists()` would go through WorkOrder's
        CompanyScopedManager, which returns nothing when no request has set
        the tenant contextvar — a management command or a shell session would
        see every template as unlocked and happily mutate audit evidence in
        place. This TestCase never sets the contextvar, so it is exactly that
        situation.
        """
        template = ChecklistTemplateFactory()
        lock_template(template)

        assert current_company_id.get() is None
        assert template.is_locked() is True


class FlowpacSeedHelperTests(TestCase):
    """Build item 5: a realistic template for reuse in tests/seeds."""

    def test_creates_a_realistic_three_item_template(self):
        company = CompanyFactory()

        template = create_flowpac_inspeccion_semanal(company=company)

        assert template.name == "Flowpac inspección semanal"
        # .unscoped(): a plain model TestCase never sets the tenant
        # contextvar (only CurrentCompanyMiddleware does, on a real
        # request) — the scoped default manager would see nothing here.
        items = list(
            ChecklistTemplateItem.objects.unscoped().filter(template=template).order_by("order")
        )
        assert [item.order for item in items] == [1, 2, 3]
        assert items[1].item_type == ChecklistTemplateItem.ItemType.NUMERIC
        assert items[1].unit == "bar"


class ChecklistTemplateItemOrderUniquenessTests(TestCase):
    """A duplicate (template, order) must never persist — it is the TOCTOU
    landmine an independent review flagged in services.add_item's "read max,
    insert max+1" order assignment: without a DB-level constraint, two
    concurrent adds on the same template could both win the read and insert
    the same order, staying silent until a later fork/edit crashes on
    `_corresponding_item`'s `.get()`.

    The constraint is DEFERRED (checked at commit, not per-statement) so
    services.move_item's single bulk_update swap of two items' `order`
    stays legal — that swap is already exercised by
    test_services.MoveItemTests. `SET CONSTRAINTS ALL IMMEDIATE` forces the
    deferred check to run here, inside the test's own transaction, instead
    of only at a real commit TestCase never performs.
    """

    def test_duplicate_order_within_one_template_is_rejected(self):
        template = ChecklistTemplateFactory()
        ChecklistTemplateItemFactory(template=template, order=1)

        with pytest.raises(IntegrityError), transaction.atomic():
            ChecklistTemplateItemFactory(template=template, order=1)
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_same_order_is_allowed_across_two_templates(self):
        template_a = ChecklistTemplateFactory()
        template_b = ChecklistTemplateFactory()

        ChecklistTemplateItemFactory(template=template_a, order=1)
        ChecklistTemplateItemFactory(template=template_b, order=1)

        assert ChecklistTemplateItem.objects.unscoped().filter(order=1).count() == 2


class ChecklistTemplateSingleForkTests(TestCase):
    """Review finding 03-1: one fork per parent, enforced by the database.

    Two supervisors editing the same locked template at the same time used to
    be able to create two rival "version 2" siblings, each carrying half the
    edits, with nothing to say which one the next work order should snapshot.
    `services.get_editable_version` now serializes on the parent row; this
    constraint is the structural backstop, in the same spirit as
    UNIQUE(plan, due_date) behind the scheduler's get_or_create.
    """

    def test_a_second_fork_of_the_same_parent_is_rejected(self):
        parent = ChecklistTemplateFactory(version=1)
        ChecklistTemplateFactory(company=parent.company, version=2, parent=parent)

        with pytest.raises(IntegrityError), transaction.atomic():
            ChecklistTemplateFactory(company=parent.company, version=2, parent=parent)

    def test_many_root_templates_without_a_parent_are_fine(self):
        """The constraint is partial: NULL parents must stay unconstrained, or
        the second template a company ever creates would fail."""
        company = CompanyFactory()
        ChecklistTemplateFactory(company=company, parent=None)
        ChecklistTemplateFactory(company=company, parent=None)

        assert ChecklistTemplate.objects.unscoped().filter(parent__isnull=True).count() == 2

    def test_a_chain_of_versions_is_still_allowed(self):
        """v1 -> v2 -> v3 is one fork per parent, not two forks of v1."""
        v1 = ChecklistTemplateFactory(version=1)
        v2 = ChecklistTemplateFactory(company=v1.company, version=2, parent=v1)
        v3 = ChecklistTemplateFactory(company=v1.company, version=3, parent=v2)

        assert v3.parent_id == v2.pk
