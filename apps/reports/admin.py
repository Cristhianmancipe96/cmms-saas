from django.contrib import admin

from apps.reports.models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    """Read-only, permanently.

    A delivery log is a record of what happened. An editable one is a record of
    what somebody says happened, which is worth nothing to the auditor it
    exists for.
    """

    list_display = ["sent_at", "company", "kind", "recipient", "status"]
    list_filter = ["status", "kind", "channel", "company"]
    search_fields = ["recipient", "subject"]

    def get_queryset(self, request):
        if request.user.is_platform_admin:
            return self.model.objects.unscoped().select_related("company", "sent_by")
        return super().get_queryset(request).select_related("company", "sent_by")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
