from django.contrib import admin

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only, and add-less, permanently.

    The model itself refuses every write after the insert, so this class is not
    what makes the table immutable — it is what stops a superuser from meeting
    that refusal as a 500 page. The interesting one is `has_add_permission`:
    a hand-written audit row is a forged one.
    """

    list_display = ["created_at", "company", "actor_label", "action", "model_label", "object_id"]
    list_filter = ["action", "model_label", "company"]
    search_fields = ["object_repr", "actor_label"]
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        if request.user.is_platform_admin:
            return self.model.objects.unscoped().select_related("company", "user")
        return super().get_queryset(request).select_related("company", "user")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
