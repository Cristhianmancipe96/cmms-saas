from django.db import models

from apps.assets.models import AssetCategory
from apps.core.tenancy import CompanyScopedModel


class ChecklistTemplate(CompanyScopedModel):
    name = models.CharField("nombre", max_length=200)
    category = models.ForeignKey(
        AssetCategory,
        on_delete=models.SET_NULL,
        related_name="checklist_templates",
        verbose_name="categoría",
        null=True,
        blank=True,
    )
    version = models.PositiveIntegerField("versión", default=1)
    is_active = models.BooleanField("activa", default=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="next_versions",
        verbose_name="versión anterior",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(CompanyScopedModel.Meta):
        ordering = ["name", "-version"]
        constraints = [
            # One fork per parent, enforced by the database. `services.
            # get_editable_version` pairs this with `select_for_update` on the
            # parent and a "does a fork already exist?" read, the same
            # structural shape as the scheduler's UNIQUE(plan, due_date) +
            # get_or_create: two concurrent edits of the same locked template
            # converge on ONE version n+1 instead of racing into two siblings
            # that both claim to be it. Partial (parent IS NOT NULL) because
            # every root template — and every `duplicate_template` copy — has
            # a NULL parent and must stay unconstrained.
            models.UniqueConstraint(
                fields=["parent"],
                condition=models.Q(parent__isnull=False),
                name="checklisttemplate_unique_parent",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"

    def is_locked(self) -> bool:
        """True once a work order references this template version — its
        items became audit evidence the moment that happened (CLAUDE.md rule
        4) and must never be mutated in place again.

        NOT `self.work_orders.exists()`: that reverse relation is built on
        WorkOrder's own CompanyScopedManager, which silently returns nothing
        outside a request context (apps/core/tenancy.py). A lock that
        evaporates in a management command or a shell session is worse than
        no lock at all — it would let an edit mutate evidence in place and
        report success. Same reasoning as `Asset.has_documents()`.

        The import is function-level to keep the app pair acyclic: work
        orders point at checklists (the snapshot's provenance FK), not the
        other way round.
        """
        from apps.workorders.models import WorkOrder

        return WorkOrder.objects.unscoped().filter(checklist_template_id=self.pk).exists()


class ChecklistTemplateItem(CompanyScopedModel):
    class ItemType(models.TextChoices):
        CHECK = "check", "Check"
        NUMERIC = "numeric", "Numérico"
        TEXT = "text", "Texto"

    template = models.ForeignKey(
        ChecklistTemplate, on_delete=models.CASCADE, related_name="items", verbose_name="plantilla"
    )
    order = models.PositiveIntegerField("orden")
    text = models.CharField("texto", max_length=500)
    item_type = models.CharField(
        "tipo", max_length=10, choices=ItemType.choices, default=ItemType.CHECK
    )
    unit = models.CharField("unidad", max_length=30, blank=True, default="")
    min_value = models.DecimalField(
        "valor mínimo", max_digits=10, decimal_places=2, null=True, blank=True
    )
    max_value = models.DecimalField(
        "valor máximo", max_digits=10, decimal_places=2, null=True, blank=True
    )
    # blank=True: without it, a ModelForm checkbox for this field is
    # required=True, so unchecking "obligatorio" (a legitimate False value)
    # would fail validation as a missing field instead of saving False.
    required = models.BooleanField("obligatorio", default=True, blank=True)

    class Meta(CompanyScopedModel.Meta):
        ordering = ["template", "order"]
        constraints = [
            # deferrable=DEFERRED: move_item (services.py) swaps two items'
            # `order` inside one transaction — a plain (non-deferred)
            # constraint would reject the transient duplicate mid-swap. This
            # also closes a TOCTOU window in add_item's "read current max,
            # then insert max+1" order assignment: two concurrent adds on
            # the same template can otherwise both compute the same max and
            # insert the same order, which stays silent until a later
            # fork/edit crashes on `_corresponding_item`'s .get(). With this
            # constraint the second insert fails loudly at commit instead.
            models.UniqueConstraint(
                fields=["template", "order"],
                name="checklisttemplateitem_unique_template_order",
                deferrable=models.Deferrable.DEFERRED,
            )
        ]

    def __str__(self) -> str:
        return self.text
