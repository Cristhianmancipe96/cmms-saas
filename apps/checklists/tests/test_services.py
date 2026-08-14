from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.checklists import services
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem
from apps.checklists.tests.factories import ChecklistTemplateFactory, ChecklistTemplateItemFactory


def _field_values(item: ChecklistTemplateItem) -> dict:
    return {field.name: getattr(item, field.name) for field in ChecklistTemplateItem._meta.fields}


class GetEditableVersionUnlockedTests(TestCase):
    """Acceptance criterion 2: an unused (unlocked) template edits in place —
    version number unchanged, same row returned.
    """

    def test_returns_same_template_unchanged(self):
        template = ChecklistTemplateFactory(version=1)

        target = services.get_editable_version(template)

        assert target.pk == template.pk
        assert target.version == 1


class GetEditableVersionLockedTests(TestCase):
    """Acceptance criterion 1: editing a locked (used) template forks
    version n+1 with copied items; the parent — and its items — stay
    byte-identical in the database.

    `is_locked` is forced True via mock.patch.object since no work-order
    model exists yet to create a real lock (brief 05).
    """

    def setUp(self):
        self.template = ChecklistTemplateFactory(version=1, is_active=True)
        self.item_a = ChecklistTemplateItemFactory(
            template=self.template,
            order=1,
            text="Nivel de aceite",
            item_type=ChecklistTemplateItem.ItemType.CHECK,
        )
        self.item_b = ChecklistTemplateItemFactory(
            template=self.template,
            order=2,
            text="Presión",
            item_type=ChecklistTemplateItem.ItemType.NUMERIC,
            unit="bar",
            min_value=Decimal("5.00"),
            max_value=Decimal("7.00"),
        )
        # Snapshot every field of the parent's items before the fork, to
        # prove afterward they are byte-identical — not just "similar".
        self.original_a = _field_values(
            ChecklistTemplateItem.objects.unscoped().get(pk=self.item_a.pk)
        )
        self.original_b = _field_values(
            ChecklistTemplateItem.objects.unscoped().get(pk=self.item_b.pk)
        )

    @patch.object(ChecklistTemplate, "is_locked", return_value=True)
    def test_forks_new_version_with_copied_items(self, mock_locked):
        target = services.get_editable_version(self.template)

        assert target.pk != self.template.pk
        assert target.version == self.template.version + 1
        assert target.parent_id == self.template.pk
        assert target.is_active is True

    @patch.object(ChecklistTemplate, "is_locked", return_value=True)
    def test_parent_is_deactivated_and_untouched(self, mock_locked):
        services.get_editable_version(self.template)

        parent = ChecklistTemplate.objects.unscoped().get(pk=self.template.pk)
        assert parent.is_active is False
        assert parent.name == self.template.name
        assert parent.version == 1  # the parent's own version number never changes

    @patch.object(ChecklistTemplate, "is_locked", return_value=True)
    def test_parent_items_are_byte_identical_after_editing_the_fork(self, mock_locked):
        target = services.get_editable_version(self.template)
        # .unscoped(): this TestCase never sets the tenant contextvar (only
        # CurrentCompanyMiddleware does, on a real request) — `target.items`
        # is built on ChecklistTemplateItem's own CompanyScopedManager and
        # would silently see nothing here.
        target_item_1 = ChecklistTemplateItem.objects.unscoped().get(template=target, order=1)
        # Apply an edit on the fork, exactly as a view would after forking —
        # the whole point of the rule is that this must never reach the parent.
        services.update_item(
            target,
            target_item_1,
            text="Nivel de aceite EDITADO",
            item_type=ChecklistTemplateItem.ItemType.CHECK,
        )

        reloaded_a = ChecklistTemplateItem.objects.unscoped().get(pk=self.item_a.pk)
        reloaded_b = ChecklistTemplateItem.objects.unscoped().get(pk=self.item_b.pk)

        assert _field_values(reloaded_a) == self.original_a
        assert _field_values(reloaded_b) == self.original_b

    @patch.object(ChecklistTemplate, "is_locked", return_value=True)
    def test_new_version_items_are_separate_rows_with_same_content(self, mock_locked):
        target = services.get_editable_version(self.template)

        new_items = list(
            ChecklistTemplateItem.objects.unscoped().filter(template=target).order_by("order")
        )
        assert len(new_items) == 2
        assert new_items[0].pk != self.item_a.pk
        assert new_items[0].text == self.item_a.text
        assert new_items[1].pk != self.item_b.pk
        assert new_items[1].unit == "bar"
        assert new_items[1].min_value == Decimal("5.00")

    @patch.object(ChecklistTemplate, "is_locked", return_value=True)
    def test_forking_a_fork_chains_off_it_and_never_touches_the_grandparent(self, mock_locked):
        # is_locked is mocked at the class level, so the freshly forked
        # `target` also reports locked — a second fork must chain v2 -> v3,
        # not v1 -> v3, and must leave v1 exactly as the first fork left it.
        target = services.get_editable_version(self.template)
        second_target = services.get_editable_version(target)

        assert second_target.pk != target.pk
        assert second_target.parent_id == target.pk
        assert second_target.version == 3
        grandparent = ChecklistTemplate.objects.unscoped().get(pk=self.template.pk)
        assert grandparent.version == 1
        assert grandparent.is_active is False


class AddItemTests(TestCase):
    def test_add_item_on_unlocked_template_mutates_in_place(self):
        template = ChecklistTemplateFactory(version=1)

        target, item = services.add_item(
            template, text="Nuevo ítem", item_type=ChecklistTemplateItem.ItemType.CHECK
        )

        assert target.pk == template.pk
        assert item.order == 1
        assert item.template_id == template.pk

    def test_add_item_assigns_next_order(self):
        template = ChecklistTemplateFactory(version=1)
        ChecklistTemplateItemFactory(template=template, order=1)
        ChecklistTemplateItemFactory(template=template, order=2)

        _target, item = services.add_item(
            template, text="Tercero", item_type=ChecklistTemplateItem.ItemType.CHECK
        )

        assert item.order == 3

    @patch.object(ChecklistTemplate, "is_locked", return_value=True)
    def test_add_item_on_locked_template_forks_and_leaves_parent_item_count_unchanged(
        self, mock_locked
    ):
        template = ChecklistTemplateFactory(version=1)
        ChecklistTemplateItemFactory(template=template, order=1)

        target, new_item = services.add_item(
            template, text="Nuevo ítem", item_type=ChecklistTemplateItem.ItemType.CHECK
        )

        assert target.pk != template.pk
        assert ChecklistTemplateItem.objects.unscoped().filter(template=template).count() == 1
        assert ChecklistTemplateItem.objects.unscoped().filter(template=target).count() == 2
        assert new_item.template_id == target.pk

    def test_add_check_item_does_not_require_a_unit(self):
        template = ChecklistTemplateFactory()

        _target, item = services.add_item(
            template, text="Chequeo simple", item_type=ChecklistTemplateItem.ItemType.CHECK
        )

        assert item.unit == ""

    def test_add_numeric_item_without_unit_is_rejected(self):
        template = ChecklistTemplateFactory()

        with pytest.raises(ValidationError):
            services.add_item(
                template,
                text="Presión",
                item_type=ChecklistTemplateItem.ItemType.NUMERIC,
                min_value=1,
                max_value=5,
            )
        assert ChecklistTemplateItem.objects.unscoped().filter(template=template).count() == 0


class MoveItemTests(TestCase):
    """Acceptance criterion 3: order persists after a move."""

    def setUp(self):
        self.template = ChecklistTemplateFactory()
        self.item_1 = ChecklistTemplateItemFactory(template=self.template, order=1, text="Uno")
        self.item_2 = ChecklistTemplateItemFactory(template=self.template, order=2, text="Dos")
        self.item_3 = ChecklistTemplateItemFactory(template=self.template, order=3, text="Tres")

    def test_move_down_swaps_with_next_item_and_persists(self):
        services.move_item(self.template, self.item_1, direction=1)

        reloaded_1 = ChecklistTemplateItem.objects.unscoped().get(pk=self.item_1.pk)
        reloaded_2 = ChecklistTemplateItem.objects.unscoped().get(pk=self.item_2.pk)
        assert reloaded_1.order == 2
        assert reloaded_2.order == 1

    def test_move_up_swaps_with_previous_item_and_persists(self):
        services.move_item(self.template, self.item_2, direction=-1)

        reloaded_1 = ChecklistTemplateItem.objects.unscoped().get(pk=self.item_1.pk)
        reloaded_2 = ChecklistTemplateItem.objects.unscoped().get(pk=self.item_2.pk)
        assert reloaded_1.order == 2
        assert reloaded_2.order == 1

    def test_move_up_at_top_is_a_no_op(self):
        services.move_item(self.template, self.item_1, direction=-1)

        reloaded_1 = ChecklistTemplateItem.objects.unscoped().get(pk=self.item_1.pk)
        assert reloaded_1.order == 1

    def test_move_down_at_bottom_is_a_no_op(self):
        services.move_item(self.template, self.item_3, direction=1)

        reloaded_3 = ChecklistTemplateItem.objects.unscoped().get(pk=self.item_3.pk)
        assert reloaded_3.order == 3

    @patch.object(ChecklistTemplate, "is_locked", return_value=True)
    def test_move_on_locked_template_forks_and_parent_order_is_untouched(self, mock_locked):
        target = services.move_item(self.template, self.item_1, direction=1)

        parent_item_1 = ChecklistTemplateItem.objects.unscoped().get(pk=self.item_1.pk)
        assert parent_item_1.order == 1  # parent's copy never moves
        target_items = list(
            ChecklistTemplateItem.objects.unscoped().filter(template=target).order_by("order")
        )
        assert [item.text for item in target_items] == ["Dos", "Uno", "Tres"]


class NumericItemValidationTests(TestCase):
    """Acceptance criterion 4: numeric items require a unit and min <= max,
    rejected with a Spanish message.
    """

    def test_missing_unit_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            services.validate_numeric_item(unit="", min_value=1, max_value=10)
        assert "unidad" in str(excinfo.value)

    def test_blank_unit_is_rejected(self):
        with pytest.raises(ValidationError):
            services.validate_numeric_item(unit="   ", min_value=1, max_value=10)

    def test_missing_min_is_rejected(self):
        with pytest.raises(ValidationError):
            services.validate_numeric_item(unit="bar", min_value=None, max_value=10)

    def test_missing_max_is_rejected(self):
        with pytest.raises(ValidationError):
            services.validate_numeric_item(unit="bar", min_value=1, max_value=None)

    def test_min_greater_than_max_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            services.validate_numeric_item(unit="bar", min_value=10, max_value=5)
        assert "mínimo" in str(excinfo.value)

    def test_min_equal_to_max_is_allowed(self):
        services.validate_numeric_item(unit="bar", min_value=5, max_value=5)

    def test_valid_range_passes(self):
        services.validate_numeric_item(unit="bar", min_value=5, max_value=10)


class DuplicateTemplateTests(TestCase):
    def test_duplicate_creates_independent_version_1_with_copied_items(self):
        template = ChecklistTemplateFactory(version=1)
        ChecklistTemplateItemFactory(template=template, order=1, text="Uno")

        duplicate = services.duplicate_template(template)

        assert duplicate.pk != template.pk
        assert duplicate.version == 1
        assert duplicate.parent is None
        assert duplicate.name == f"{template.name} (copia)"
        assert ChecklistTemplateItem.objects.unscoped().filter(template=duplicate).count() == 1

    @patch.object(ChecklistTemplate, "is_locked", return_value=True)
    def test_duplicate_of_a_locked_template_does_not_fork_the_original(self, mock_locked):
        template = ChecklistTemplateFactory(version=1)
        ChecklistTemplateItemFactory(template=template, order=1)

        services.duplicate_template(template)

        original = ChecklistTemplate.objects.unscoped().get(pk=template.pk)
        assert original.is_active is True
        assert original.version == 1


class DeactivateTemplateTests(TestCase):
    def test_deactivate_flips_is_active_without_touching_items(self):
        template = ChecklistTemplateFactory(is_active=True)
        item = ChecklistTemplateItemFactory(template=template, order=1)

        services.deactivate_template(template)

        reloaded = ChecklistTemplate.objects.unscoped().get(pk=template.pk)
        reloaded_item = ChecklistTemplateItem.objects.unscoped().get(pk=item.pk)
        assert reloaded.is_active is False
        assert reloaded_item.order == 1

    @patch.object(ChecklistTemplate, "is_locked", return_value=True)
    def test_deactivate_of_a_locked_template_does_not_fork(self, mock_locked):
        template = ChecklistTemplateFactory(is_active=True, version=1)

        services.deactivate_template(template)

        reloaded = ChecklistTemplate.objects.unscoped().get(pk=template.pk)
        assert reloaded.is_active is False
        assert reloaded.version == 1
        assert ChecklistTemplate.objects.unscoped().filter(parent=template).count() == 0
