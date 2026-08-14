from django import forms

from apps.assets.models import AssetCategory
from apps.checklists import services
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem


class ChecklistTemplateForm(forms.ModelForm):
    class Meta:
        model = ChecklistTemplate
        fields = ["name", "category"]

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].required = False
        if company is not None:
            # Same reasoning as AssetForm.__init__ (apps/assets/forms.py): a
            # ModelForm's default FK queryset is built once at import time,
            # before any request sets the tenant contextvar, and stays
            # permanently empty otherwise.
            self.fields["category"].queryset = AssetCategory.objects.unscoped().filter(
                company=company
            )


class ChecklistTemplateItemForm(forms.ModelForm):
    class Meta:
        model = ChecklistTemplateItem
        fields = ["text", "item_type", "unit", "min_value", "max_value", "required"]

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("item_type") == ChecklistTemplateItem.ItemType.NUMERIC:
            services.validate_numeric_item(
                unit=cleaned_data.get("unit", ""),
                min_value=cleaned_data.get("min_value"),
                max_value=cleaned_data.get("max_value"),
            )
        return cleaned_data
