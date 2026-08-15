"""Failure reports: the product's front door.

Everything else in this system is written by someone with a job title — a
supervisor plans, a technician executes. This table is written by whoever
happened to be standing in front of a machine that stopped, including the
office `staff` role that may not open a work order at all. That is the point:
the report is cheap and open, and turning it into work is the supervisor's
decision, recorded as such.

**A request never holds a pointer to its work order.** The link lives on the
work order (`WorkOrder.source_request`, a OneToOneField), which is what makes
"one request, at most one OT" a `UNIQUE` index rather than a promise the
conversion code makes — the same structural move as the scheduler's
`UNIQUE(plan, due_date)` (CLAUDE.md rule 5). Two clicks race for one index
slot, and one of them loses in the database, not in a code review.
"""

from django.conf import settings
from django.db import models

from apps.assets.models import Asset
from apps.core.tenancy import CompanyScopedModel
from apps.requests_.storage import request_photo_upload_path


class MaintenanceRequest(CompanyScopedModel):
    class Status(models.TextChoices):
        NUEVA = "nueva", "Nueva"
        CONVERTIDA = "convertida", "Convertida"
        RECHAZADA = "rechazada", "Rechazada"

    # PROTECT: a request is the origin story of a corrective work order, and an
    # equipment record that can be deleted out from under it would leave the
    # audit log pointing at a machine nobody can name. Equipment is *dado de
    # baja*, not deleted, exactly like brief 04 decided for work orders.
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="maintenance_requests",
        verbose_name="equipo",
    )
    # PROTECT for the same reason as WorkOrder.completed_by: "who reported
    # this" is a fact the row exists to hold.
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="maintenance_requests",
        verbose_name="reportada por",
    )
    description = models.TextField("¿Qué está fallando?", max_length=2000)
    # Plain FileField, not ImageField, for the reason spelled out in
    # apps/workorders/models.py: Django's ImageField runs its own Pillow check
    # first and surfaces an English message instead of ours.
    photo = models.FileField(
        "foto",
        upload_to=request_photo_upload_path,
        max_length=255,
        blank=True,
        help_text="Opcional. Una foto de la falla ahorra un viaje.",
    )
    status = models.CharField(
        "estado", max_length=20, choices=Status.choices, default=Status.NUEVA
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="revisada por",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField("revisada el", null=True, blank=True)
    review_note = models.TextField("motivo del rechazo", blank=True, default="", max_length=2000)
    created_at = models.DateTimeField("reportada el", auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(CompanyScopedModel.Meta):
        verbose_name = "solicitud de mantenimiento"
        verbose_name_plural = "solicitudes de mantenimiento"
        ordering = ["-created_at", "-id"]
        indexes = [
            *CompanyScopedModel.Meta.indexes,
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["reported_by", "-created_at"]),
        ]
        constraints = [
            # A rejection without a reason is a shrug with a timestamp. The
            # form asks for the note; this is what makes the rule hold for
            # every other way a row could be written.
            models.CheckConstraint(
                condition=~models.Q(status="rechazada") | ~models.Q(review_note=""),
                name="maintenancerequest_rejection_needs_a_note",
            )
        ]

    def __str__(self) -> str:
        # The machine's code, not its id. This string is what the audit log
        # freezes as `object_repr`, and «Solicitud #1 · 3» answers nobody's
        # question a year later. Costs one query when the asset is not already
        # loaded, on a path that writes a row anyway.
        return f"Solicitud #{self.pk} · {self.asset.code}"

    # --- Presentation helpers ----------------------------------------------

    BADGE_MODIFIERS = {
        Status.NUEVA: "nueva",
        Status.CONVERTIDA: "convertida",
        Status.RECHAZADA: "rechazada",
    }

    @property
    def badge_modifier(self) -> str:
        return self.BADGE_MODIFIERS.get(self.status, "nueva")

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.NUEVA

    @property
    def summary(self) -> str:
        """First line of the description, for a list row."""
        first_line = self.description.strip().splitlines()[0] if self.description.strip() else ""
        return first_line[:80]
