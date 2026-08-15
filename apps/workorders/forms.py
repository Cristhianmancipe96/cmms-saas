from decimal import Decimal

from django import forms

from apps.accounts.models import User
from apps.assets.storage import reencode_image, validate_image_upload
from apps.checklists.models import ChecklistTemplate
from apps.workorders.models import WorkOrder, WorkOrderPhoto
from apps.workorders.services import ASSIGNABLE_ROLES


def _assignable_users(company):
    return User.objects.filter(
        company=company, is_active=True, role__in=ASSIGNABLE_ROLES
    ).order_by("role", "username")


class CorrectiveWorkOrderForm(forms.ModelForm):
    """The «reportar una falla» form: a machine broke, someone has to go.

    The asset comes from the URL, never from a field — that is what keeps a
    crafted POST from filing a corrective work order against another
    company's equipment. `type` and `origin` are fixed by the view for the
    same reason: they are facts about how this row was born, not user input.
    """

    class Meta:
        model = WorkOrder
        fields = [
            "priority",
            "due_date",
            "assigned_to",
            "failure_description",
            "checklist_template",
        ]
        widgets = {
            "due_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "failure_description": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {"failure_description": "¿Qué está fallando?"}
        help_texts = {
            "assigned_to": "Puedes dejarlo vacío y asignarla después.",
            "checklist_template": (
                "Opcional. Se copia a la OT al crearla y ya no cambia, aunque "
                "después edites la plantilla."
            ),
        }

    def __init__(self, *args, company=None, asset=None, can_assign=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].required = False
        self.fields["checklist_template"].required = False
        self.fields["failure_description"].required = True

        if not can_assign:
            # A technician reports the breakdown; deciding who fixes it is the
            # supervisor's call (`assign` in the transition matrix). Removing
            # the field, rather than ignoring it, is what makes a hand-crafted
            # POST unable to self-assign.
            del self.fields["assigned_to"]

        if company is not None:
            # `.unscoped().filter(company=...)`: a ModelForm builds its FK
            # querysets when the class is first imported, long before any
            # request sets the tenant contextvar, so a scoped queryset here is
            # permanently empty (see apps/assets/forms.py).
            if can_assign:
                self.fields["assigned_to"].queryset = _assignable_users(company)
            templates = (
                ChecklistTemplate.objects.unscoped()
                .filter(company=company, is_active=True)
                .order_by("name", "-version")
            )
            self.fields["checklist_template"].queryset = templates
            if asset is not None and not self.is_bound:
                # Prefill from the asset: the checklist an operator wants for a
                # broken compressor is almost always the one written for
                # compressors.
                self.fields["checklist_template"].initial = (
                    templates.filter(category_id=asset.category_id).first()
                )


class WorkOrderAssignForm(forms.Form):
    assignee = forms.ModelChoiceField(
        label="Asignar a", queryset=User.objects.none(), empty_label="Elige un responsable"
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["assignee"].queryset = _assignable_users(company)


class WorkOrderCancelForm(forms.Form):
    reason = forms.CharField(
        label="Motivo de la cancelación",
        widget=forms.Textarea(attrs={"rows": 3}),
        min_length=3,
        max_length=2000,
    )


class WorkOrderCompleteForm(forms.Form):
    """Closing numbers. Everything is optional except what the checklist
    already enforces — a technician who cannot find the invoice for a part
    must still be able to close the work order today.

    Costs are whole pesos: COP has no practical subunit, and an integer field
    is also what makes "no negative money" a database-level fact rather than a
    form-level wish (acceptance criterion 6).
    """

    work_done = forms.CharField(
        label="Trabajo realizado",
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
        max_length=5000,
    )
    downtime_minutes = forms.IntegerField(
        label="Tiempo de parada (min)",
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
    )
    labor_cost_cop = forms.IntegerField(
        label="Mano de obra (COP)",
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
    )
    parts_cost_cop = forms.IntegerField(
        label="Repuestos (COP)",
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
    )
    meter_reading_hours = forms.DecimalField(
        label="Horómetro al cierre (h)",
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"step": "0.01", "min": "0", "inputmode": "decimal", "autocomplete": "off"}
        ),
        help_text="Se guarda como lectura del equipo.",
    )

    def __init__(self, *args, tracks_meter: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        if not tracks_meter:
            # Asking a machine nobody meters for its hours is noise, and a
            # field that is never right is a field people learn to ignore.
            del self.fields["meter_reading_hours"]

    def payload(self) -> dict:
        """Only the fields the operator actually filled.

        `transition` defaults every missing key to the value already stored,
        so sending `None` for an untouched cost would quietly erase it.
        """
        data = {key: value for key, value in self.cleaned_data.items() if value not in (None, "")}
        return data


class WorkOrderPhotoForm(forms.ModelForm):
    """Evidence upload. Same three-step validation as asset photos — size,
    then extension, then real image bytes — followed by a full Pillow
    re-encode that drops EXIF (including GPS) and any active payload.
    """

    class Meta:
        model = WorkOrderPhoto
        fields = ["image", "caption"]
        labels = {"image": "Foto"}
        widgets = {
            # capture="environment" opens the rear camera straight from the
            # phone instead of the gallery: one tap from "I see the problem" to
            # "it is documented".
            "image": forms.ClearableFileInput(
                attrs={"accept": "image/*", "capture": "environment"}
            ),
            "caption": forms.TextInput(attrs={"placeholder": "Ej. Rodamiento dañado"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["caption"].required = False

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and hasattr(image, "content_type"):
            extension = validate_image_upload(image)
            image = reencode_image(image, extension)
        return image
