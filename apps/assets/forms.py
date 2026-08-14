from django import forms

from apps.accounts.models import Site
from apps.assets.models import Asset, AssetCategory, AssetDocument
from apps.assets.storage import (
    IMAGE_EXTENSIONS,
    reencode_image,
    validate_document_upload,
    validate_image_upload,
)


class AssetCategoryForm(forms.ModelForm):
    class Meta:
        model = AssetCategory
        fields = ["name"]


class AssetForm(forms.ModelForm):
    """Core "hoja de vida" fields. `status`/`baja_reason` are out of scope here —
    they only change through the dedicated dar-de-baja action, never a plain edit.
    """

    class Meta:
        model = Asset
        fields = [
            "site",
            "category",
            "code",
            "name",
            "brand",
            "model",
            "serial_number",
            "purchase_date",
            "warranty_until",
            "criticality",
            "location_detail",
            "main_photo",
        ]
        widgets = {
            "purchase_date": forms.DateInput(attrs={"type": "date"}),
            "warranty_until": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            # Not self.fields["site"].queryset.filter(...): ModelForm builds
            # that base queryset by calling the scoped manager's
            # get_queryset() once, when this form CLASS is first imported —
            # long before any request sets the tenant contextvar (apps/core/
            # tenancy.py). It is permanently .none(), and .filter() on
            # .none() stays empty, so every site/category choice would be
            # rejected as invalid forever. Build a fresh queryset instead.
            self.fields["site"].queryset = Site.objects.unscoped().filter(company=company)
            self.fields["category"].queryset = AssetCategory.objects.unscoped().filter(
                company=company
            )

    def clean_main_photo(self):
        photo = self.cleaned_data.get("main_photo")
        # Only a freshly-uploaded InMemoryUploadedFile/TemporaryUploadedFile needs
        # validation — leaving the field untouched on edit re-submits the existing
        # ImageFieldFile, which has no .content_type and must not be re-validated.
        if photo and hasattr(photo, "content_type"):
            extension = validate_image_upload(photo)
            photo = reencode_image(photo, extension)
        return photo


def parse_specs_from_post(post_data) -> list[dict[str, str]]:
    """Zip the parallel spec_key[]/spec_value[] lists HTMX rows submit, in
    the order they appear in the form, dropping only fully-empty rows.
    """
    keys = post_data.getlist("spec_key")
    values = post_data.getlist("spec_value")
    specs = []
    for key, value in zip(keys, values, strict=False):
        key, value = key.strip(), value.strip()
        if key or value:
            specs.append({"key": key, "value": value})
    return specs


class AssetDocumentForm(forms.ModelForm):
    class Meta:
        model = AssetDocument
        fields = ["kind", "file", "name"]

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")
        if uploaded_file and hasattr(uploaded_file, "content_type"):
            extension = validate_document_upload(uploaded_file)
            if extension in IMAGE_EXTENSIONS:
                uploaded_file = reencode_image(uploaded_file, extension)
        return uploaded_file


class AssetBajaForm(forms.Form):
    reason = forms.CharField(
        label="Motivo",
        widget=forms.Textarea(attrs={"rows": 3}),
        min_length=3,
        max_length=2000,
    )
