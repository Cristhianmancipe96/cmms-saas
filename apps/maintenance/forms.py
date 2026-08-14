from django import forms

from apps.accounts.models import User
from apps.checklists.models import ChecklistTemplate
from apps.maintenance.models import (
    INTERVAL_PRESETS,
    MaintenancePlan,
    MeterReading,
    validate_monotonic_reading,
)

CUSTOM_INTERVAL = "custom"


class MaintenancePlanForm(forms.ModelForm):
    """Two frequency modes in one form, both always visible.

    No JavaScript toggles the sections: the app ships without a build step
    and is used on weak plant-floor networks, so the form stays legible and
    submittable with scripting unavailable. Both fieldsets render, the
    legends say which one applies, and `clean()` both enforces the right one
    and blanks the other so a plan can never carry contradictory frequency
    data.
    """

    interval_preset = forms.ChoiceField(
        label="Cada cuánto",
        required=False,
        choices=[("", "---------")]
        + [(str(days), label) for days, label in INTERVAL_PRESETS]
        + [(CUSTOM_INTERVAL, "Personalizado (indica los días)")],
    )

    class Meta:
        model = MaintenancePlan
        fields = [
            "name",
            "kind",
            "frequency_type",
            "interval_days",
            "next_due_date",
            "meter_interval_hours",
            "checklist_template",
            "default_assignee",
            "estimated_minutes",
            "is_active",
        ]
        widgets = {
            "next_due_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "meter_interval_hours": forms.NumberInput(
                attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"}
            ),
            "interval_days": forms.NumberInput(attrs={"min": "1", "inputmode": "numeric"}),
            "estimated_minutes": forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
        }
        help_texts = {
            "interval_days": "Solo si elegiste «Personalizado» arriba.",
            "next_due_date": "Fecha de la primera OT que debe generarse.",
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["interval_days"].required = False
        self.fields["next_due_date"].required = False
        self.fields["meter_interval_hours"].required = False
        self.fields["checklist_template"].required = False
        self.fields["default_assignee"].required = False

        if company is not None:
            # `.unscoped().filter(company=...)`, same reasoning as AssetForm
            # and ChecklistTemplateForm: a ModelForm builds its FK querysets at
            # import time, before any request sets the tenant contextvar, so a
            # scoped queryset here is permanently empty. Filtering explicitly
            # by company is also what keeps another tenant's checklists and
            # technicians out of these dropdowns.
            self.fields["checklist_template"].queryset = (
                ChecklistTemplate.objects.unscoped()
                .filter(company=company, is_active=True)
                .order_by("name", "-version")
            )
            self.fields["default_assignee"].queryset = (
                User.objects.filter(
                    company=company, is_active=True, role=User.Role.TECHNICIAN
                ).order_by("username")
            )

        if not self.is_bound:
            self.fields["interval_preset"].initial = self._initial_preset()

    def _initial_preset(self) -> str:
        interval_days = getattr(self.instance, "interval_days", None)
        if interval_days is None:
            return ""
        if any(interval_days == days for days, _label in INTERVAL_PRESETS):
            return str(interval_days)
        return CUSTOM_INTERVAL

    def clean(self):
        cleaned_data = super().clean()
        frequency_type = cleaned_data.get("frequency_type")

        if frequency_type == MaintenancePlan.FrequencyType.CALENDAR:
            self._clean_calendar(cleaned_data)
            cleaned_data["meter_interval_hours"] = None
        elif frequency_type == MaintenancePlan.FrequencyType.METER:
            if not cleaned_data.get("meter_interval_hours"):
                self.add_error(
                    "meter_interval_hours",
                    "Indica cada cuántas horas de uso se debe hacer el mantenimiento.",
                )
            cleaned_data["interval_days"] = None
            cleaned_data["next_due_date"] = None
        return cleaned_data

    def _clean_calendar(self, cleaned_data) -> None:
        preset = cleaned_data.get("interval_preset")
        if preset and preset != CUSTOM_INTERVAL:
            cleaned_data["interval_days"] = int(preset)
        elif preset == CUSTOM_INTERVAL and not cleaned_data.get("interval_days"):
            self.add_error("interval_days", "Indica cada cuántos días se repite el plan.")
        elif not preset and not cleaned_data.get("interval_days"):
            self.add_error("interval_preset", "Elige cada cuánto se repite el plan.")

        if not cleaned_data.get("next_due_date"):
            self.add_error("next_due_date", "Indica la fecha del próximo vencimiento.")


class MeterReadingForm(forms.ModelForm):
    """Quick entry from the asset detail screen: one number, one button."""

    class Meta:
        model = MeterReading
        fields = ["reading_hours"]
        widgets = {
            "reading_hours": forms.NumberInput(
                attrs={
                    "step": "0.01",
                    "min": "0",
                    "inputmode": "decimal",
                    "autocomplete": "off",
                    "placeholder": "Ej. 1250.5",
                }
            )
        }

    def __init__(self, *args, asset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.asset = asset

    def clean_reading_hours(self):
        reading_hours = self.cleaned_data["reading_hours"]
        if self.asset is not None:
            # Raises with the same sentence the model guard uses, but bound to
            # this field so it renders next to the input instead of at the top.
            validate_monotonic_reading(self.asset.pk, reading_hours)
        return reading_hours
