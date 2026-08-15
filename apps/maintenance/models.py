from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from apps.assets.models import Asset
from apps.checklists.models import ChecklistTemplate
from apps.core.tenancy import CompanyScopedModel

# The presets the plan form offers. 30/90/180/365 are *named* periods —
# "mensual", "trimestral", "semestral", "anual" — and the scheduler advances
# them by calendar months, not by that many days, so Jan 31 lands on Feb 28
# instead of drifting to Mar 2 (acceptance criterion 3). See
# `services.advance_due_date`, the single place that knows this.
INTERVAL_PRESETS: list[tuple[int, str]] = [
    (7, "Semanal (7 días)"),
    (15, "Quincenal (15 días)"),
    (30, "Mensual"),
    (90, "Trimestral"),
    (180, "Semestral"),
    (365, "Anual"),
]


class MaintenancePlan(CompanyScopedModel):
    class Kind(models.TextChoices):
        PREVENTIVO = "preventivo", "Preventivo"
        INSPECCION = "inspeccion", "Inspección"
        LUBRICACION = "lubricacion", "Lubricación"
        CALIBRACION = "calibracion", "Calibración"

    class FrequencyType(models.TextChoices):
        CALENDAR = "calendar", "Por calendario"
        METER = "meter", "Por horómetro"

    asset = models.ForeignKey(
        Asset, on_delete=models.CASCADE, related_name="maintenance_plans", verbose_name="equipo"
    )
    name = models.CharField("nombre", max_length=200)
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices, default=Kind.PREVENTIVO)
    frequency_type = models.CharField(
        "frecuencia", max_length=10, choices=FrequencyType.choices, default=FrequencyType.CALENDAR
    )
    interval_days = models.PositiveIntegerField(
        "cada cuántos días", null=True, blank=True, validators=[MinValueValidator(1)]
    )
    meter_interval_hours = models.DecimalField(
        "cada cuántas horas",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    checklist_template = models.ForeignKey(
        ChecklistTemplate,
        on_delete=models.SET_NULL,
        related_name="maintenance_plans",
        verbose_name="plantilla de checklist",
        null=True,
        blank=True,
        help_text="Al crear cada OT se usa la última versión activa de esta plantilla.",
    )
    default_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="responsable por defecto",
        null=True,
        blank=True,
    )
    next_due_date = models.DateField("próximo vencimiento", null=True, blank=True)
    # The meter reading the last generated work order was based on. The
    # scheduler compares the newest reading against this value, so a meter
    # plan never "catches up" the way a calendar plan does: 95h -> 210h with a
    # 100h interval is one work order, not two (acceptance criterion 4). The
    # create view seeds it with the asset's current reading so adding a plan
    # to a machine that already has 5.000 h doesn't fire immediately.
    hours_at_last_generated_wo = models.DecimalField(
        "horómetro de la última OT generada",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
    )
    estimated_minutes = models.PositiveIntegerField(
        "duración estimada (min)", null=True, blank=True
    )
    is_active = models.BooleanField("activo", default=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(CompanyScopedModel.Meta):
        verbose_name = "plan de mantenimiento"
        verbose_name_plural = "planes de mantenimiento"
        ordering = ["name"]
        indexes = [
            *CompanyScopedModel.Meta.indexes,
            models.Index(fields=["next_due_date"]),
        ]
        constraints = [
            # A calendar plan without an interval or without a next due date,
            # and a meter plan without an hour interval, are not "incomplete
            # drafts" — they are rows the scheduler cannot act on at all. The
            # form rejects them, and so does the database, so a shell or admin
            # write can't create a plan that silently never generates anything.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        frequency_type="calendar",
                        interval_days__isnull=False,
                        next_due_date__isnull=False,
                    )
                    | models.Q(frequency_type="meter", meter_interval_hours__isnull=False)
                ),
                name="maintenanceplan_frequency_fields_required",
                # Spanish, because ModelForm surfaces a violated constraint
                # straight to the user as a non-field error.
                violation_error_message=(
                    "Falta la frecuencia del plan: indica los días y el próximo "
                    "vencimiento (calendario) o las horas (horómetro)."
                ),
            ),
            # interval_days >= 1 is what makes the catch-up loop in
            # services._generate_calendar terminate: every iteration strictly
            # advances next_due_date, so the loop is bounded by the number of
            # days between next_due_date and the horizon.
            models.CheckConstraint(
                condition=models.Q(interval_days__isnull=True) | models.Q(interval_days__gte=1),
                name="maintenanceplan_interval_days_positive",
                violation_error_message="El intervalo en días debe ser de al menos 1.",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(meter_interval_hours__isnull=True)
                    | models.Q(meter_interval_hours__gt=0)
                ),
                name="maintenanceplan_meter_interval_positive",
                violation_error_message="El intervalo en horas debe ser mayor que cero.",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_calendar(self) -> bool:
        return self.frequency_type == self.FrequencyType.CALENDAR

    @property
    def frequency_label(self) -> str:
        """Human frequency for list rows: "Mensual", "Cada 45 días", "Cada 250 h"."""
        if self.is_calendar:
            if self.interval_days is None:
                return "Sin frecuencia"
            for days, label in INTERVAL_PRESETS:
                if days == self.interval_days:
                    return label
            return f"Cada {self.interval_days} días"
        if self.meter_interval_hours is None:
            return "Sin frecuencia"
        return f"Cada {normalize_hours(self.meter_interval_hours)} h"


def normalize_hours(hours: Decimal) -> str:
    """Render hours without trailing zeros: 100.00 -> "100", 12.50 -> "12.5"."""
    quantized = Decimal(hours).normalize()
    if quantized == quantized.to_integral_value():
        quantized = quantized.to_integral_value()
    return f"{quantized:f}"


def validate_monotonic_reading(asset_id: int, reading_hours, exclude_pk=None) -> None:
    """An hour meter never runs backwards, so neither may our record of it.

    Enforced from three places on purpose: the quick-entry form (so the
    technician gets the message next to the field), `MeterReading.save()` (so
    a shell, a management command or the admin cannot bypass it), and here in
    one function so all three say exactly the same sentence.
    """
    if reading_hours is None or asset_id is None:
        return
    previous = MeterReading.objects.unscoped().filter(asset_id=asset_id)
    if exclude_pk is not None:
        previous = previous.exclude(pk=exclude_pk)
    highest = previous.aggregate(models.Max("reading_hours"))["reading_hours__max"]
    if highest is not None and reading_hours < highest:
        # A plain (not dict-form) ValidationError on purpose: `add_error`
        # rejects a dict-form error when it is raised from a field cleaner,
        # and the quick-entry form wants this message attached to the
        # `reading_hours` input, not floating at the top of the panel.
        raise ValidationError(
            f"La lectura ({normalize_hours(reading_hours)} h) no puede ser menor "
            f"que la última registrada ({normalize_hours(highest)} h)."
        )


def record_reading(
    *,
    asset,
    reading_hours,
    source: str,
    recorded_by=None,
    read_at=None,
) -> "MeterReading":
    """The ONE way an hour-meter reading is written. Serialized per machine.

    `validate_monotonic_reading` reads the current maximum and the insert
    happens after it — a classic TOCTOU window. Two technicians submitting
    2.000 h and 1.900 h at the same moment both read "highest = 1.800",
    both pass, and both commit: the meter has silently run backwards, and
    every meter-driven plan on that asset now schedules off a number that
    never happened.

    `select_for_update` on the *asset* row is what closes it. The lock is
    taken on the machine rather than on the readings, because the invariant
    is "one writer per machine at a time" and there is no reading row to
    lock when the first one is being inserted. Both writers of readings —
    the quick-entry panel (`source=manual`) and closing a work order
    (`source=work_order`) — come through here, so the serialization holds
    for every path, not just the one the UI happens to use today.
    """
    from apps.assets.models import Asset

    with transaction.atomic():
        # .unscoped(): the lock must also be taken from a management command
        # or a service call that runs outside the request cycle, where the
        # scoped manager would match zero rows and quietly lock nothing —
        # the failure mode is a lock that looks taken and isn't.
        locked_asset = Asset.objects.unscoped().select_for_update().filter(pk=asset.pk).first()
        if locked_asset is None:
            raise ValidationError("El equipo ya no existe.")
        validate_monotonic_reading(locked_asset.pk, reading_hours)
        return MeterReading.objects.create(
            company_id=locked_asset.company_id,
            asset_id=locked_asset.pk,
            reading_hours=reading_hours,
            source=source,
            recorded_by=recorded_by,
            **({"read_at": read_at} if read_at is not None else {}),
        )


class MeterReading(CompanyScopedModel):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        WORK_ORDER = "work_order", "Orden de trabajo"

    asset = models.ForeignKey(
        Asset, on_delete=models.CASCADE, related_name="meter_readings", verbose_name="equipo"
    )
    reading_hours = models.DecimalField(
        "horómetro (h)",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    # default (not auto_now_add): brief 05 records the reading a technician
    # took when they closed the work order, which is not necessarily the
    # instant the row is written.
    read_at = models.DateTimeField("fecha de lectura", default=timezone.now)
    source = models.CharField(
        "origen", max_length=20, choices=Source.choices, default=Source.MANUAL
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="registrada por",
        null=True,
        blank=True,
    )

    class Meta(CompanyScopedModel.Meta):
        verbose_name = "lectura de horómetro"
        verbose_name_plural = "lecturas de horómetro"
        ordering = ["-read_at", "-id"]
        indexes = [
            *CompanyScopedModel.Meta.indexes,
            models.Index(fields=["asset", "-read_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.asset_id} · {normalize_hours(self.reading_hours)} h"

    def clean(self):
        super().clean()
        validate_monotonic_reading(self.asset_id, self.reading_hours, exclude_pk=self.pk)

    def save(self, *args, **kwargs):
        # Defense in depth: the same guard the form runs, repeated at the
        # model layer so it also holds from the shell, the admin, a management
        # command or a future n8n-triggered import.
        validate_monotonic_reading(self.asset_id, self.reading_hours, exclude_pk=self.pk)
        return super().save(*args, **kwargs)
