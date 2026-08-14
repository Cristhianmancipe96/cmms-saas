"""Versioning and validation rules for checklist templates and their items.

CLAUDE.md rule 4: verified work orders are audit evidence, and checklist
results are snapshots — later edits to a template must never alter a past
work order's evidence. Every mutation here (item add/edit/reorder) funnels
through `get_editable_version`, the one place that decides whether an edit
lands on the template you asked for or on a freshly forked n+1 (acceptance
criteria 1 and 2).

Every read below goes through `ChecklistTemplateItem.objects.unscoped()`
with an explicit `template=` filter, and every write to a FK uses the
`_id` field (e.g. `category_id=`) instead of assigning a fetched relation.
Two reasons, both about this module having to work outside a request too —
from a pytest test, a management command, or a future Celery task — not
only from the one HTTP view that happens to call it today:

1. `template.items`, `template.category` and `template.parent` are all
   built on their model's own `CompanyScopedManager` (apps/core/tenancy.py)
   — the *only* manager on a `CompanyScopedModel`, so Django also uses it
   as the base manager for relation traversal. Outside a request (no
   tenant contextvar set), it silently returns nothing. Same reasoning as
   `Asset.has_documents()` in apps/assets/models.py.
2. Using the plain `_id` avoids that lookup entirely — no query, no
   contextvar dependency — for values we already hold on the instance.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem


def validate_numeric_item(*, unit: str, min_value, max_value) -> None:
    """Acceptance criterion 4: numeric items require a unit and min <= max."""
    if not unit or not unit.strip():
        raise ValidationError("Los ítems numéricos requieren una unidad.")
    if min_value is None or max_value is None:
        raise ValidationError("Los ítems numéricos requieren un valor mínimo y un valor máximo.")
    if min_value > max_value:
        raise ValidationError("El valor mínimo debe ser menor o igual al valor máximo.")


def _items_of(template: ChecklistTemplate):
    return ChecklistTemplateItem.objects.unscoped().filter(template=template).order_by("order")


def _copy_items(source_template: ChecklistTemplate, target_template: ChecklistTemplate) -> None:
    ChecklistTemplateItem.objects.bulk_create(
        [
            ChecklistTemplateItem(
                company_id=target_template.company_id,
                template=target_template,
                order=item.order,
                text=item.text,
                item_type=item.item_type,
                unit=item.unit,
                min_value=item.min_value,
                max_value=item.max_value,
                required=item.required,
            )
            for item in _items_of(source_template)
        ]
    )


@transaction.atomic
def get_editable_version(template: ChecklistTemplate) -> ChecklistTemplate:
    """Acceptance criteria 1 and 2. If `template` is locked (already used by
    a work order), its rows — and its items' rows — must never be mutated:
    fork version n+1 with copied items and retire the parent instead. An
    unused template edits in place: return it unchanged.
    """
    if not template.is_locked():
        return template

    new_version = ChecklistTemplate.objects.create(
        company_id=template.company_id,
        name=template.name,
        category_id=template.category_id,
        version=template.version + 1,
        is_active=True,
        parent=template,
    )
    _copy_items(template, new_version)

    template.is_active = False
    template.save(update_fields=["is_active"])
    return new_version


def _corresponding_item(
    target_template: ChecklistTemplate, item: ChecklistTemplateItem
) -> ChecklistTemplateItem:
    """After a possible fork, `item` may still be the retired parent's row.
    Its copy on `target_template` was created with the same `order` — the
    only stable correlation key carried across the copy.
    """
    if item.template_id == target_template.pk:
        return item
    return ChecklistTemplateItem.objects.unscoped().get(template=target_template, order=item.order)


@transaction.atomic
def add_item(
    template: ChecklistTemplate,
    *,
    text: str,
    item_type: str,
    unit: str = "",
    min_value=None,
    max_value=None,
    required: bool = True,
) -> tuple[ChecklistTemplate, ChecklistTemplateItem]:
    if item_type == ChecklistTemplateItem.ItemType.NUMERIC:
        validate_numeric_item(unit=unit, min_value=min_value, max_value=max_value)

    target = get_editable_version(template)
    max_order = (
        ChecklistTemplateItem.objects.unscoped()
        .filter(template=target)
        .aggregate(Max("order"))["order__max"]
    )
    item = ChecklistTemplateItem.objects.create(
        company_id=target.company_id,
        template=target,
        order=(max_order or 0) + 1,
        text=text,
        item_type=item_type,
        unit=unit,
        min_value=min_value,
        max_value=max_value,
        required=required,
    )
    return target, item


@transaction.atomic
def update_item(
    template: ChecklistTemplate,
    item: ChecklistTemplateItem,
    *,
    text: str,
    item_type: str,
    unit: str = "",
    min_value=None,
    max_value=None,
    required: bool = True,
) -> tuple[ChecklistTemplate, ChecklistTemplateItem]:
    if item_type == ChecklistTemplateItem.ItemType.NUMERIC:
        validate_numeric_item(unit=unit, min_value=min_value, max_value=max_value)

    target = get_editable_version(template)
    target_item = _corresponding_item(target, item)
    target_item.text = text
    target_item.item_type = item_type
    target_item.unit = unit
    target_item.min_value = min_value
    target_item.max_value = max_value
    target_item.required = required
    target_item.save()
    return target, target_item


@transaction.atomic
def move_item(
    template: ChecklistTemplate, item: ChecklistTemplateItem, *, direction: int
) -> ChecklistTemplate:
    """Acceptance criterion 3. `direction` is -1 (up/earlier) or +1
    (down/later). A no-op past either end of the list.
    """
    target = get_editable_version(template)
    target_item = _corresponding_item(target, item)
    items = list(_items_of(target))
    index = items.index(target_item)
    swap_index = index + direction
    if 0 <= swap_index < len(items):
        neighbor = items[swap_index]
        target_item.order, neighbor.order = neighbor.order, target_item.order
        # .unscoped(): Manager.bulk_update() runs its UPDATE through
        # self.get_queryset() — the scoped one outside a request context —
        # same landmine as the reads this module already routes around (see
        # the module docstring). The scoped call would silently update zero
        # rows here.
        ChecklistTemplateItem.objects.unscoped().bulk_update([target_item, neighbor], ["order"])
    return target


@transaction.atomic
def duplicate_template(template: ChecklistTemplate) -> ChecklistTemplate:
    """The builder's explicit "duplicate" action always starts a brand new,
    independent lineage (version 1, no parent) — unlike `get_editable_version`,
    which forks *within* a lineage to protect a locked version's items.
    """
    new_template = ChecklistTemplate.objects.create(
        company_id=template.company_id,
        name=f"{template.name} (copia)",
        category_id=template.category_id,
        version=1,
        is_active=True,
        parent=None,
    )
    _copy_items(template, new_template)
    return new_template


def deactivate_template(template: ChecklistTemplate) -> None:
    """A status flip only — it never touches items, so it never needs to
    fork even a locked template (unlike the mutations above).
    """
    template.is_active = False
    template.save(update_fields=["is_active"])
