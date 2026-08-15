"""Work orders: the product's evidence table.

Three invariants are enforced here, at the model layer, rather than in the
views that happen to call them today (CLAUDE.md rules 3 and 4):

1. **A `verificada` work order is frozen.** Its own row, its checklist items
   and its photos reject every write and every delete once it is verified —
   from a view, the admin, a shell, a management command or a future n8n
   import alike. Audit evidence that only some code paths respect is not
   evidence.
2. **The checklist is a snapshot, not a pointer.** `WorkOrderChecklistItem`
   carries copies of the template's text/type/range/required fields, so
   editing a template later cannot retro-edit what a technician signed off.
   `checklist_template` records *which version* was copied — provenance for
   the auditor's question "what exactly was this person asked to check?".
3. **Who executed is recorded, not inferred.** `completed_by` is written when
   the work is finished and is what `services.transition` compares against
   when someone tries to verify (CLAUDE.md rule 3).

The state machine itself — who may move a work order from where to where —
lives in `services.py`, the single entry point for every transition.
"""

from django.conf import settings
from django.db import models

from apps.assets.models import Asset
from apps.core.tenancy import CompanyScopedManager, CompanyScopedModel
from apps.workorders.storage import work_order_photo_upload_path

# The literal is needed by the querysets below, which are defined before
# WorkOrder.Status exists. Status.VERIFICADA is built from it, so the two can
# never drift apart.
VERIFIED_STATUS = "verificada"

SEALED_MESSAGE = (
    "Esta OT ya fue verificada: es evidencia de auditoría y no se puede "
    "modificar ni eliminar."
)


class WorkOrderSealedError(Exception):
    """Raised on any attempt to write to, or delete, verified work-order data."""


class SealedGuardQuerySet(models.QuerySet):
    """Extends the seal to bulk writes.

    `Model.save()`/`Model.delete()` overrides are invisible to
    `queryset.update()` and `queryset.delete()`, which go straight to SQL. A
    guard that a one-line `.update(status="abierta")` walks past is not a
    guard, so the same question is asked here before the statement is built.

    Subclasses declare `sealed_filter`: the lookup that matches rows belonging
    to a verified work order.
    """

    sealed_filter: dict = {}

    def _reject_if_any_row_is_sealed(self) -> None:
        if self.filter(**self.sealed_filter).exists():
            raise WorkOrderSealedError(SEALED_MESSAGE)

    def update(self, **kwargs):
        self._reject_if_any_row_is_sealed()
        return super().update(**kwargs)

    def delete(self):
        self._reject_if_any_row_is_sealed()
        return super().delete()


class WorkOrderQuerySet(SealedGuardQuerySet):
    sealed_filter = {"status": VERIFIED_STATUS}


class WorkOrderChildQuerySet(SealedGuardQuerySet):
    sealed_filter = {"work_order__status": VERIFIED_STATUS}


def _work_order_is_sealed(work_order_id) -> bool:
    """True if that work order is already verified.

    `.unscoped()` on purpose: the seal must hold outside a request too, where
    the scoped manager matches nothing and would report every work order as
    editable (apps/core/tenancy.py). The read is an indexed primary-key
    lookup, paid once per write to a table that sees a handful of writes per
    work order in its lifetime.
    """
    if work_order_id is None:
        return False
    return WorkOrder.objects.unscoped().filter(pk=work_order_id, status=VERIFIED_STATUS).exists()


class WorkOrder(CompanyScopedModel):
    class Type(models.TextChoices):
        PREVENTIVO = "preventivo", "Preventivo"
        CORRECTIVO = "correctivo", "Correctivo"
        INSPECCION = "inspeccion", "Inspección"

    class Origin(models.TextChoices):
        PLAN = "plan", "Plan"
        MANUAL = "manual", "Manual"
        SOLICITUD = "solicitud", "Solicitud"

    class Status(models.TextChoices):
        ABIERTA = "abierta", "Abierta"
        ASIGNADA = "asignada", "Asignada"
        EN_PROGRESO = "en_progreso", "En progreso"
        TERMINADA = "terminada", "Terminada"
        VERIFICADA = VERIFIED_STATUS, "Verificada"
        CANCELADA = "cancelada", "Cancelada"

    class Priority(models.TextChoices):
        BAJA = "baja", "Baja"
        MEDIA = "media", "Media"
        ALTA = "alta", "Alta"
        CRITICA = "critica", "Crítica"

    # PROTECT on both FKs: a work order is audit evidence (CLAUDE.md rule 4),
    # so neither the equipment it documents nor the plan that scheduled it may
    # be deleted out from under it. The maintenance views translate the
    # resulting ProtectedError into a Spanish "deactivate instead" message.
    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="work_orders", verbose_name="equipo"
    )
    plan = models.ForeignKey(
        "maintenance.MaintenancePlan",
        on_delete=models.PROTECT,
        related_name="work_orders",
        verbose_name="plan",
        null=True,
        blank=True,
        help_text="Vacío en las órdenes correctivas y manuales.",
    )
    # PROTECT, for the same reason and one more: this FK is the provenance of
    # the snapshot below — the answer to "which version of the checklist was
    # this technician actually given?". A cascade or a SET_NULL here would
    # erase that answer while the evidence it explains lives on. It is also
    # what makes `ChecklistTemplate.is_locked()` a real lock instead of a
    # placeholder: a template with work orders can no longer be edited in
    # place, only forked.
    checklist_template = models.ForeignKey(
        "checklists.ChecklistTemplate",
        on_delete=models.PROTECT,
        related_name="work_orders",
        verbose_name="plantilla de checklist",
        null=True,
        blank=True,
        help_text="Versión exacta de la plantilla que se copió al crear la OT.",
    )
    type = models.CharField("tipo", max_length=20, choices=Type.choices, default=Type.PREVENTIVO)
    origin = models.CharField("origen", max_length=20, choices=Origin.choices, default=Origin.PLAN)
    status = models.CharField(
        "estado", max_length=20, choices=Status.choices, default=Status.ABIERTA
    )
    priority = models.CharField(
        "prioridad", max_length=20, choices=Priority.choices, default=Priority.MEDIA
    )
    due_date = models.DateField("fecha programada", null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_work_orders",
        verbose_name="asignada a",
        null=True,
        blank=True,
    )
    started_at = models.DateTimeField("iniciada", null=True, blank=True)
    finished_at = models.DateTimeField("terminada", null=True, blank=True)
    # PROTECT, unlike assigned_to: "who did this work" is the fact CLAUDE.md
    # rule 3 is checked against, so it must not become NULL when a user row is
    # removed. If it could, deleting a user would silently hand that user's own
    # supervisor account permission to verify their own work.
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="ejecutada por",
        null=True,
        blank=True,
    )
    failure_description = models.TextField("descripción de la falla", blank=True, default="")
    work_done = models.TextField("trabajo realizado", blank=True, default="")
    downtime_minutes = models.PositiveIntegerField("tiempo de parada (min)", null=True, blank=True)
    labor_cost_cop = models.PositiveIntegerField("mano de obra (COP)", null=True, blank=True)
    parts_cost_cop = models.PositiveIntegerField("repuestos (COP)", null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="verificada por",
        null=True,
        blank=True,
    )
    verified_at = models.DateTimeField("verificada el", null=True, blank=True)
    cancel_reason = models.TextField("motivo de cancelación", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CompanyScopedManager.from_queryset(WorkOrderQuerySet)()

    class Meta(CompanyScopedModel.Meta):
        verbose_name = "orden de trabajo"
        verbose_name_plural = "órdenes de trabajo"
        ordering = ["-due_date", "-id"]
        indexes = [
            *CompanyScopedModel.Meta.indexes,
            # "Mis OTs" and the supervisor list both read by these two.
            models.Index(fields=["status", "due_date"]),
            models.Index(fields=["assigned_to", "status"]),
        ]
        constraints = [
            # CLAUDE.md rule 5. Postgres treats NULLs as distinct in a unique
            # index, so corrective work orders (plan IS NULL) are unaffected:
            # the constraint only ever binds plan-generated rows.
            models.UniqueConstraint(
                fields=["plan", "due_date"], name="workorder_unique_plan_due_date"
            )
        ]

    def __str__(self) -> str:
        return f"OT #{self.pk} · {self.asset_id} · {self.due_date}"

    # --- The seal -----------------------------------------------------------

    @property
    def is_sealed(self) -> bool:
        return self.status == self.Status.VERIFICADA

    def _sealed_in_db(self) -> bool:
        if self._state.adding or self.pk is None:
            return False
        return _work_order_is_sealed(self.pk)

    def save(self, *args, **kwargs):
        # The *stored* status is what decides, not the in-memory one: the
        # verify transition itself writes `verificada` onto a row that is still
        # `terminada` in the database, and must go through. Every write after
        # that reads `verificada` here and is refused — including an attempt to
        # walk the status back to `en_progreso`.
        if self._sealed_in_db():
            raise WorkOrderSealedError(SEALED_MESSAGE)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_sealed or self._sealed_in_db():
            raise WorkOrderSealedError(SEALED_MESSAGE)
        return super().delete(*args, **kwargs)

    # --- Presentation helpers ----------------------------------------------

    # DESIGN.md names the badge modifiers after the states as an operator reads
    # them, which is not one-to-one with the stored values ("terminada" is
    # "hecha" on screen, "en_progreso" hyphenates). One map here beats an
    # {% if %} ladder repeated in four templates.
    BADGE_MODIFIERS = {
        Status.ABIERTA: "abierta",
        Status.ASIGNADA: "asignada",
        Status.EN_PROGRESO: "en-proceso",
        Status.TERMINADA: "hecha",
        Status.VERIFICADA: "verificada",
        Status.CANCELADA: "cancelada",
    }

    @property
    def badge_modifier(self) -> str:
        return self.BADGE_MODIFIERS.get(self.status, "abierta")

    # A work order stops being "late" the moment the work is done: what happens
    # after `terminada` is the supervisor's queue, not the technician's.
    OPEN_STATUSES = (Status.ABIERTA, Status.ASIGNADA, Status.EN_PROGRESO)

    # The work actually happened. Brief 07's report exists only for these: the
    # detail screen offers the button, and apps/reports/documents.py resolves
    # the URL, from this one tuple rather than from two `{% if %}`s that could
    # drift apart.
    DONE_STATUSES = (Status.TERMINADA, Status.VERIFICADA)

    def is_overdue(self, today) -> bool:
        return (
            self.due_date is not None
            and self.due_date < today
            and self.status in self.OPEN_STATUSES
        )

    @property
    def total_cost_cop(self) -> int | None:
        if self.labor_cost_cop is None and self.parts_cost_cop is None:
            return None
        return (self.labor_cost_cop or 0) + (self.parts_cost_cop or 0)


class WorkOrderChecklistItem(CompanyScopedModel):
    """One frozen copy of a template item, plus what the technician answered.

    Every field above `result` is a copy taken at creation time, never a
    lookup: that is what makes acceptance criterion 4 ("editing the template
    changes nothing in the work order") true by construction instead of by
    convention.
    """

    class ItemType(models.TextChoices):
        CHECK = "check", "Check"
        NUMERIC = "numeric", "Numérico"
        TEXT = "text", "Texto"

    class Result(models.TextChoices):
        OK = "ok", "OK"
        FALLA = "falla", "Falla"
        NA = "na", "N/A"

    work_order = models.ForeignKey(
        WorkOrder, on_delete=models.CASCADE, related_name="checklist_items", verbose_name="OT"
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
    required = models.BooleanField("obligatorio", default=True, blank=True)

    result = models.CharField(
        "resultado", max_length=10, choices=Result.choices, blank=True, default=""
    )
    numeric_value = models.DecimalField(
        "valor medido", max_digits=10, decimal_places=2, null=True, blank=True
    )
    note = models.TextField("observación", blank=True, default="")

    objects = CompanyScopedManager.from_queryset(WorkOrderChildQuerySet)()

    class Meta(CompanyScopedModel.Meta):
        verbose_name = "ítem de checklist de OT"
        verbose_name_plural = "ítems de checklist de OT"
        ordering = ["work_order", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["work_order", "order"], name="workorderchecklistitem_unique_wo_order"
            )
        ]

    def __str__(self) -> str:
        return self.text

    def save(self, *args, **kwargs):
        if _work_order_is_sealed(self.work_order_id):
            raise WorkOrderSealedError(SEALED_MESSAGE)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if _work_order_is_sealed(self.work_order_id):
            raise WorkOrderSealedError(SEALED_MESSAGE)
        return super().delete(*args, **kwargs)

    @property
    def is_answered(self) -> bool:
        """What "respondido" means per item type — the rule `complete` checks.

        A text item's answer *is* its note: it has no OK/Falla to press, so
        requiring a `result` on it would make required text items impossible
        to satisfy. A numeric item marked N/A is answered without a value;
        otherwise the measurement is the answer.
        """
        if self.item_type == self.ItemType.TEXT:
            return bool(self.note.strip())
        if self.item_type == self.ItemType.NUMERIC and self.result != self.Result.NA:
            return bool(self.result) and self.numeric_value is not None
        return bool(self.result)

    @property
    def is_failure(self) -> bool:
        return self.result == self.Result.FALLA

    @property
    def range_label(self) -> str:
        """"5 – 7 bar", for the hint under a numeric input."""
        if self.min_value is None or self.max_value is None:
            return self.unit
        return f"{self.min_value:f} – {self.max_value:f} {self.unit}".strip()


class WorkOrderPhoto(CompanyScopedModel):
    """Photographic evidence attached to a work order.

    `image` is a plain FileField for the same reason `Asset.main_photo` is:
    Django's ImageField would run its own Pillow check before our validator
    and surface Django's generic English message instead of ours. The upload
    is validated and re-encoded by `forms.WorkOrderPhotoForm` through
    apps/assets/storage.py — size, extension, magic bytes, then a full
    re-encode that drops EXIF and any active payload.
    """

    work_order = models.ForeignKey(
        WorkOrder, on_delete=models.CASCADE, related_name="photos", verbose_name="OT"
    )
    image = models.FileField(
        "foto", upload_to=work_order_photo_upload_path, max_length=255
    )
    caption = models.CharField("descripción", max_length=200, blank=True, default="")
    taken_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="tomada por",
        null=True,
        blank=True,
    )
    taken_at = models.DateTimeField("tomada el", auto_now_add=True)

    objects = CompanyScopedManager.from_queryset(WorkOrderChildQuerySet)()

    class Meta(CompanyScopedModel.Meta):
        verbose_name = "foto de OT"
        verbose_name_plural = "fotos de OT"
        ordering = ["taken_at", "id"]

    def __str__(self) -> str:
        return self.caption or f"Foto {self.pk}"

    def save(self, *args, **kwargs):
        if _work_order_is_sealed(self.work_order_id):
            raise WorkOrderSealedError(SEALED_MESSAGE)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if _work_order_is_sealed(self.work_order_id):
            raise WorkOrderSealedError(SEALED_MESSAGE)
        return super().delete(*args, **kwargs)
