"""The work-order table — created here as the *shell* brief 05 specifies.

Brief 04 (build item 4) needs somewhere for the scheduler to write, but the
state machine, the checklist snapshot, the photos and the whole mobile
execution UI belong to brief 05. So this module carries brief 05's field
list and nothing else: no transitions, no immutability guards, no views.
Brief 05 fills the behaviour in without a schema churn.

The one piece of behaviour that *is* brief 04's, because CLAUDE.md rule 5
makes it a structural guarantee rather than a service-layer convention, is
`UNIQUE(plan, due_date)`: the scheduler pairs it with `get_or_create` so a
second run — or a run that resumes after a crash halfway through — can
never produce a duplicate work order.
"""

from django.conf import settings
from django.db import models

from apps.assets.models import Asset
from apps.core.tenancy import CompanyScopedModel


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
        VERIFICADA = "verificada", "Verificada"
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

    class Meta(CompanyScopedModel.Meta):
        verbose_name = "orden de trabajo"
        verbose_name_plural = "órdenes de trabajo"
        ordering = ["-due_date", "-id"]
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
