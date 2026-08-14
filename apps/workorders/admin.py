from django.contrib import admin

from apps.workorders.models import WorkOrder


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    """Read-only for now. Brief 05 owns the transition matrix and the
    immutability guards; until those exist, letting an `is_staff` user edit
    a work order from the admin would bypass rules that are not written yet.
    """

    list_display = ["pk", "company", "asset", "type", "status", "due_date", "assigned_to"]
    list_filter = ["company", "status", "type", "origin"]

    def get_queryset(self, request):
        if request.user.is_platform_admin:
            return self.model.objects.unscoped()
        return super().get_queryset(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
