from django.contrib import admin

from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem


class ChecklistTemplateItemInline(admin.TabularInline):
    """Read-only. Items must be edited through the builder (checklist_item_
    create/update/move_*), whose views always route through services.py so a
    locked template forks instead of mutating audit-evidence rows in place
    (CLAUDE.md rule 4). Django admin's own formset save path calls
    instance.save() directly and never touches services.py — a plain
    editable inline here would let any is_staff user bypass the lock
    entirely, silently rewriting a past work order's checklist items.
    """

    model = ChecklistTemplateItem
    extra = 0
    fields = ["order", "text", "item_type", "unit", "min_value", "max_value", "required"]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChecklistTemplate)
class ChecklistTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "version", "is_active", "category"]
    list_filter = ["company", "is_active", "category"]
    search_fields = ["name"]
    inlines = [ChecklistTemplateItemInline]

    def get_queryset(self, request):
        if request.user.is_platform_admin:
            return self.model.objects.unscoped()
        return super().get_queryset(request)
