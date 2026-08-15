from django import forms

from apps.assets.storage import reencode_image, validate_image_upload
from apps.requests_.models import MaintenanceRequest
from apps.workorders.models import WorkOrder


class MaintenanceRequestForm(forms.ModelForm):
    """The report itself: a sentence and, if there is time, a photo.

    Deliberately two fields. This form is filled standing in front of a stopped
    machine, often by someone whose job is not maintenance, and every extra
    field is a reason to walk away and tell nobody. The equipment comes from
    the URL, never from a field — the same rule as
    `CorrectiveWorkOrderForm`, and what keeps a crafted POST from filing a
    report against another company's machine.
    """

    class Meta:
        model = MaintenanceRequest
        fields = ["description", "photo"]
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Ej. La banda hace un ruido fuerte y se detiene sola.",
                    "autofocus": "autofocus",
                }
            ),
            # capture="environment" opens the rear camera straight from the
            # phone instead of the gallery: one tap from "I see the problem" to
            # "it is documented".
            "photo": forms.ClearableFileInput(
                attrs={"accept": "image/*", "capture": "environment"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = True
        self.fields["photo"].required = False

    def clean_photo(self):
        """Same three-step validation as every other upload in the product —
        size, extension, real image bytes — then a full Pillow re-encode that
        drops EXIF (including the GPS coordinates of the plant) and any active
        payload."""
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "content_type"):
            extension = validate_image_upload(photo)
            photo = reencode_image(photo, extension)
        return photo


class RequestConvertForm(forms.Form):
    """One decision: how urgent is it. Everything else the OT needs is already
    in the request (the machine) or fixed by the conversion (type, origin).

    Defaulted to `alta`, so accepting it is one click: someone walked to a
    screen to report that a machine is failing, which is not routine work.
    """

    priority = forms.ChoiceField(
        label="Prioridad de la OT",
        choices=WorkOrder.Priority.choices,
        initial=WorkOrder.Priority.ALTA,
    )


class RequestRejectForm(forms.Form):
    """Rejecting costs a sentence. That is the whole design of this form: the
    reporter is told *why*, so the next report is better than this one."""

    note = forms.CharField(
        label="Motivo del rechazo",
        widget=forms.Textarea(attrs={"rows": 3, "autofocus": "autofocus"}),
        min_length=3,
        max_length=2000,
        help_text="Lo lee quien reportó la falla.",
    )
