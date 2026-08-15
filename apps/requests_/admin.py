from django.contrib import admin

from apps.requests_.models import MaintenanceRequest


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    """Read-only, for the same reason WorkOrderAdmin is (apps/workorders/admin.py).

    Deciding a request is a transition with a permission check, a lock and an
    audit row; a free-form admin form is a way to make one without any of the
    three — and, worse here, a way to flip `status` to `convertida` without the
    work order that word promises.
    """

    list_display = ["pk", "company", "asset", "status", "reported_by", "created_at"]
    list_filter = ["company", "status"]
    search_fields = ["description"]

    def get_queryset(self, request):
        if request.user.is_platform_admin:
            return self.model.objects.unscoped().select_related("company", "asset", "reported_by")
        return super().get_queryset(request).select_related("company", "asset", "reported_by")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
