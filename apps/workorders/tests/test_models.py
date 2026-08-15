"""Model-layer guarantees: the seal, the snapshot and the money.

Every test here deliberately bypasses the views. Acceptance criterion 3 is
about what the *model* refuses, and a rule that only holds when a view
remembers to check it is not a rule — it is a habit.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory, TechnicianUserFactory
from apps.assets.tests.factories import AssetFactory
from apps.checklists import services as checklist_services
from apps.checklists.models import ChecklistTemplateItem
from apps.checklists.tests.factories import (
    ChecklistTemplateFactory,
    ChecklistTemplateItemFactory,
    create_flowpac_inspeccion_semanal,
)
from apps.maintenance.tests.factories import MaintenancePlanFactory
from apps.workorders import services
from apps.workorders.models import (
    WorkOrder,
    WorkOrderChecklistItem,
    WorkOrderPhoto,
    WorkOrderSealedError,
)
from apps.workorders.tests.factories import (
    WorkOrderChecklistItemFactory,
    WorkOrderFactory,
    WorkOrderPhotoFactory,
)


def _seal(work_order: WorkOrder) -> WorkOrder:
    """Mark a work order verified by writing the column directly.

    Going through `services.transition` would be the honest path, but this
    module tests the guard *itself*: it must fire on any verified row, however
    that row came to be — including one produced by a migration, an import or
    a code path that does not exist yet.
    """
    WorkOrder.objects.unscoped().filter(pk=work_order.pk).update(
        status=WorkOrder.Status.VERIFICADA, verified_at=timezone.now()
    )
    return WorkOrder.objects.unscoped().get(pk=work_order.pk)


class VerifiedWorkOrderIsImmutableTests(TestCase):
    """Acceptance criterion 3, the work order itself."""

    def test_saving_a_verified_work_order_raises(self):
        work_order = _seal(WorkOrderFactory())
        work_order.work_done = "Reescribiendo la evidencia"

        with pytest.raises(WorkOrderSealedError):
            work_order.save()

        assert WorkOrder.objects.unscoped().get(pk=work_order.pk).work_done == ""

    def test_walking_the_status_back_raises(self):
        """The guard reads the STORED status, not the in-memory one — otherwise
        setting `status = "en_progreso"` before saving would unseal the row."""
        work_order = _seal(WorkOrderFactory())
        work_order.status = WorkOrder.Status.EN_PROGRESO

        with pytest.raises(WorkOrderSealedError):
            work_order.save()

        assert (
            WorkOrder.objects.unscoped().get(pk=work_order.pk).status
            == WorkOrder.Status.VERIFICADA
        )

    def test_deleting_a_verified_work_order_raises(self):
        work_order = _seal(WorkOrderFactory())

        with pytest.raises(WorkOrderSealedError):
            work_order.delete()

        assert WorkOrder.objects.unscoped().filter(pk=work_order.pk).exists()

    def test_a_bulk_update_touching_a_verified_work_order_raises(self):
        """`.update()` never calls save(). A guard it walks past is not a guard."""
        work_order = _seal(WorkOrderFactory())

        with pytest.raises(WorkOrderSealedError):
            WorkOrder.objects.unscoped().filter(pk=work_order.pk).update(work_done="masivo")

        assert WorkOrder.objects.unscoped().get(pk=work_order.pk).work_done == ""

    def test_a_bulk_delete_touching_a_verified_work_order_raises(self):
        work_order = _seal(WorkOrderFactory())

        with pytest.raises(WorkOrderSealedError):
            WorkOrder.objects.unscoped().filter(pk=work_order.pk).delete()

        assert WorkOrder.objects.unscoped().filter(pk=work_order.pk).exists()

    def test_an_unverified_work_order_still_saves_normally(self):
        work_order = WorkOrderFactory()

        work_order.work_done = "Cambio de rodamiento"
        work_order.save()

        assert (
            WorkOrder.objects.unscoped().get(pk=work_order.pk).work_done
            == "Cambio de rodamiento"
        )

    def test_the_write_that_seals_the_row_is_itself_allowed(self):
        """The verify transition writes `verificada` onto a `terminada` row.
        The guard must let that one through, or nothing could ever be sealed."""
        work_order = WorkOrderFactory(status=WorkOrder.Status.TERMINADA)

        work_order.status = WorkOrder.Status.VERIFICADA
        work_order.save()

        assert (
            WorkOrder.objects.unscoped().get(pk=work_order.pk).status
            == WorkOrder.Status.VERIFICADA
        )


class VerifiedChecklistItemsAndPhotosAreImmutableTests(TestCase):
    """Acceptance criterion 3, the children. Sealing the parent is not enough
    when the evidence lives one foreign key away."""

    def setUp(self):
        self.work_order = WorkOrderFactory()
        self.item = WorkOrderChecklistItemFactory(
            work_order=self.work_order, order=1, result="ok"
        )
        self.photo = WorkOrderPhotoFactory(work_order=self.work_order, caption="Antes")
        _seal(self.work_order)

    def test_editing_a_checklist_item_raises(self):
        self.item.result = WorkOrderChecklistItem.Result.FALLA

        with pytest.raises(WorkOrderSealedError):
            self.item.save()

        assert WorkOrderChecklistItem.objects.unscoped().get(pk=self.item.pk).result == "ok"

    def test_deleting_a_checklist_item_raises(self):
        with pytest.raises(WorkOrderSealedError):
            self.item.delete()

        assert WorkOrderChecklistItem.objects.unscoped().filter(pk=self.item.pk).exists()

    def test_adding_a_checklist_item_to_a_verified_work_order_raises(self):
        with pytest.raises(WorkOrderSealedError):
            WorkOrderChecklistItemFactory(work_order=self.work_order, order=2)

    def test_editing_a_photo_raises(self):
        self.photo.caption = "Reescrito"

        with pytest.raises(WorkOrderSealedError):
            self.photo.save()

        assert WorkOrderPhoto.objects.unscoped().get(pk=self.photo.pk).caption == "Antes"

    def test_deleting_a_photo_raises(self):
        with pytest.raises(WorkOrderSealedError):
            self.photo.delete()

        assert WorkOrderPhoto.objects.unscoped().filter(pk=self.photo.pk).exists()

    def test_bulk_updating_the_items_raises(self):
        with pytest.raises(WorkOrderSealedError):
            WorkOrderChecklistItem.objects.unscoped().filter(
                work_order=self.work_order
            ).update(note="masivo")

        assert WorkOrderChecklistItem.objects.unscoped().get(pk=self.item.pk).note == ""

    def test_bulk_deleting_the_photos_raises(self):
        with pytest.raises(WorkOrderSealedError):
            WorkOrderPhoto.objects.unscoped().filter(work_order=self.work_order).delete()

        assert WorkOrderPhoto.objects.unscoped().filter(pk=self.photo.pk).exists()

    def test_items_of_an_unsealed_work_order_still_save(self):
        other = WorkOrderFactory()
        item = WorkOrderChecklistItemFactory(work_order=other, order=1)

        item.result = WorkOrderChecklistItem.Result.OK
        item.save()

        assert WorkOrderChecklistItem.objects.unscoped().get(pk=item.pk).result == "ok"


class SnapshotIndependenceTests(TestCase):
    """Acceptance criterion 4: editing the template afterwards changes nothing."""

    SNAPSHOT_FIELDS = [
        field.name
        for field in WorkOrderChecklistItem._meta.fields
        if field.name not in {"id", "work_order", "company"}
    ]

    def _snapshot_values(self, work_order) -> list[dict]:
        return [
            {name: getattr(item, name) for name in self.SNAPSHOT_FIELDS}
            for item in services.checklist_items(work_order)
        ]

    def test_the_snapshot_copies_every_template_field(self):
        template = create_flowpac_inspeccion_semanal(company=CompanyFactory())
        work_order = WorkOrderFactory(asset=AssetFactory(company=template.company))

        copied = services.snapshot_checklist(work_order, template)

        items = list(services.checklist_items(work_order))
        assert copied == 3
        assert [item.order for item in items] == [1, 2, 3]
        assert items[1].item_type == WorkOrderChecklistItem.ItemType.NUMERIC
        assert items[1].unit == "bar"
        assert items[1].min_value == Decimal("5.00")
        assert items[1].max_value == Decimal("7.00")
        assert work_order.checklist_template_id == template.pk

    def test_editing_the_template_afterwards_leaves_the_snapshot_byte_identical(self):
        template = create_flowpac_inspeccion_semanal(company=CompanyFactory())
        work_order = WorkOrderFactory(asset=AssetFactory(company=template.company))
        services.snapshot_checklist(work_order, template)
        before = self._snapshot_values(work_order)

        # Every mutation the builder offers, applied at once. The work order
        # now locks the template, so each of these forks it — which is exactly
        # the path a real supervisor's edit takes.
        source_item = ChecklistTemplateItem.objects.unscoped().get(template=template, order=1)
        target, _ = checklist_services.update_item(
            template,
            source_item,
            text="TEXTO CAMBIADO DESPUÉS",
            item_type=ChecklistTemplateItem.ItemType.CHECK,
            required=False,
        )
        checklist_services.add_item(
            target, text="Ítem nuevo", item_type=ChecklistTemplateItem.ItemType.CHECK
        )

        assert self._snapshot_values(work_order) == before

    def test_deleting_the_snapshotted_template_is_refused_by_protect(self):
        """The provenance FK is PROTECT: which version was executed must stay
        answerable for as long as the evidence exists."""
        template = ChecklistTemplateFactory()
        ChecklistTemplateItemFactory(template=template, order=1)
        work_order = WorkOrderFactory(asset=AssetFactory(company=template.company))
        services.snapshot_checklist(work_order, template)

        with pytest.raises(ProtectedError):
            template.delete()

    def test_snapshotting_onto_a_verified_work_order_is_refused(self):
        """bulk_create writes straight to SQL and never calls save(), so the
        model guard cannot see it. The service asks the question itself."""
        template = create_flowpac_inspeccion_semanal(company=CompanyFactory())
        work_order = _seal(WorkOrderFactory(asset=AssetFactory(company=template.company)))

        with pytest.raises(services.NotAllowed):
            services.snapshot_checklist(work_order, template)

        assert list(services.checklist_items(work_order)) == []

    def test_a_work_order_without_a_template_gets_no_checklist(self):
        work_order = WorkOrderFactory()

        copied = services.snapshot_checklist(work_order, None)

        assert copied == 0
        assert list(services.checklist_items(work_order)) == []
        assert work_order.checklist_template_id is None

    def test_two_work_orders_from_one_template_get_independent_copies(self):
        template = create_flowpac_inspeccion_semanal(company=CompanyFactory())
        asset = AssetFactory(company=template.company)
        first = WorkOrderFactory(asset=asset, due_date="2026-01-01")
        second = WorkOrderFactory(asset=asset, due_date="2026-02-01")
        services.snapshot_checklist(first, template)
        services.snapshot_checklist(second, template)

        item = services.checklist_items(first).first()
        item.result = WorkOrderChecklistItem.Result.FALLA
        item.save()

        assert services.checklist_items(second).first().result == ""


class WorkOrderNumericFieldTests(TestCase):
    """Acceptance criterion 6: costs and downtime are non-negative integers,
    at the database, not only in a form."""

    def test_negative_labor_cost_is_rejected_by_the_database(self):
        work_order = WorkOrderFactory()

        with pytest.raises(IntegrityError), transaction.atomic():
            WorkOrder.objects.unscoped().filter(pk=work_order.pk).update(labor_cost_cop=-1)

    def test_negative_parts_cost_is_rejected_by_the_database(self):
        work_order = WorkOrderFactory()

        with pytest.raises(IntegrityError), transaction.atomic():
            WorkOrder.objects.unscoped().filter(pk=work_order.pk).update(parts_cost_cop=-1)

    def test_negative_downtime_is_rejected_by_the_database(self):
        work_order = WorkOrderFactory()

        with pytest.raises(IntegrityError), transaction.atomic():
            WorkOrder.objects.unscoped().filter(pk=work_order.pk).update(downtime_minutes=-1)

    def test_zero_is_a_legitimate_cost(self):
        work_order = WorkOrderFactory(labor_cost_cop=0, parts_cost_cop=0, downtime_minutes=0)

        assert work_order.total_cost_cop == 0

    def test_total_cost_is_none_when_nothing_was_recorded(self):
        assert WorkOrderFactory().total_cost_cop is None

    def test_total_cost_adds_the_two_halves(self):
        work_order = WorkOrderFactory(labor_cost_cop=120_000, parts_cost_cop=80_000)

        assert work_order.total_cost_cop == 200_000


class ChecklistItemAnsweringRulesTests(TestCase):
    """What "respondido" means per item type — the rule `complete` enforces."""

    def test_an_unanswered_check_item_is_not_answered(self):
        assert WorkOrderChecklistItemFactory(result="").is_answered is False

    def test_a_check_item_with_a_result_is_answered(self):
        assert WorkOrderChecklistItemFactory(result="ok").is_answered is True

    def test_a_numeric_item_without_a_value_is_not_answered(self):
        item = WorkOrderChecklistItemFactory(
            item_type=WorkOrderChecklistItem.ItemType.NUMERIC,
            unit="bar",
            min_value=Decimal("5"),
            max_value=Decimal("7"),
            result="ok",
            numeric_value=None,
        )

        assert item.is_answered is False

    def test_a_numeric_item_marked_na_is_answered_without_a_value(self):
        item = WorkOrderChecklistItemFactory(
            item_type=WorkOrderChecklistItem.ItemType.NUMERIC,
            unit="bar",
            result=WorkOrderChecklistItem.Result.NA,
            numeric_value=None,
        )

        assert item.is_answered is True

    def test_a_text_item_is_answered_by_its_note(self):
        item = WorkOrderChecklistItemFactory(
            item_type=WorkOrderChecklistItem.ItemType.TEXT, note="Todo normal"
        )

        assert item.is_answered is True

    def test_a_text_item_with_only_whitespace_is_not_answered(self):
        item = WorkOrderChecklistItemFactory(
            item_type=WorkOrderChecklistItem.ItemType.TEXT, note="   "
        )

        assert item.is_answered is False


class WorkOrderPresentationTests(TestCase):
    def test_an_open_work_order_past_its_due_date_is_overdue(self):
        today = timezone.localdate()
        work_order = WorkOrderFactory(
            status=WorkOrder.Status.ASIGNADA, due_date=today - timedelta(days=1)
        )

        assert work_order.is_overdue(today) is True

    def test_a_finished_work_order_is_never_overdue(self):
        """Late stops being the technician's problem once the work is done."""
        today = timezone.localdate()
        work_order = WorkOrderFactory(
            status=WorkOrder.Status.TERMINADA, due_date=today - timedelta(days=30)
        )

        assert work_order.is_overdue(today) is False

    def test_a_cancelled_work_order_is_never_overdue(self):
        today = timezone.localdate()
        work_order = WorkOrderFactory(
            status=WorkOrder.Status.CANCELADA, due_date=today - timedelta(days=30)
        )

        assert work_order.is_overdue(today) is False

    def test_a_work_order_without_a_due_date_is_never_overdue(self):
        work_order = WorkOrderFactory(status=WorkOrder.Status.ABIERTA, due_date=None)

        assert work_order.is_overdue(timezone.localdate()) is False

    def test_badge_modifiers_match_the_design_system_names(self):
        assert WorkOrderFactory(status=WorkOrder.Status.EN_PROGRESO).badge_modifier == "en-proceso"
        assert WorkOrderFactory(status=WorkOrder.Status.TERMINADA).badge_modifier == "hecha"
        assert WorkOrderFactory(status=WorkOrder.Status.VERIFICADA).badge_modifier == "verificada"


class WorkOrderTenancyTests(TestCase):
    def test_a_work_order_carries_its_assets_company(self):
        company = CompanyFactory()
        asset = AssetFactory(company=company)

        work_order = WorkOrderFactory(asset=asset)

        assert work_order.company_id == company.pk

    def test_the_plan_due_date_uniqueness_still_holds(self):
        """CLAUDE.md rule 5, untouched by this brief."""
        company = CompanyFactory()
        asset = AssetFactory(company=company)
        plan = MaintenancePlanFactory(company=company, asset=asset)
        WorkOrderFactory(asset=asset, plan=plan, due_date=plan.next_due_date)

        with pytest.raises(IntegrityError), transaction.atomic():
            WorkOrderFactory(asset=asset, plan=plan, due_date=plan.next_due_date)

    def test_assigning_someone_from_another_company_is_refused(self):
        company = CompanyFactory()
        work_order = WorkOrderFactory(asset=AssetFactory(company=company))
        outsider = TechnicianUserFactory(company=CompanyFactory())
        admin = AdminUserFactory(company=company)

        with pytest.raises(services.NotAllowed):
            services.transition(work_order, services.ASSIGN, admin, assignee=outsider)
