from django.contrib import admin

from apps.workorders.models import WorkOrder


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    """Read-only, permanently.

    Not "until the rules exist" any more — they do (services.transition). The
    admin stays read-only precisely *because* they exist: every legitimate
    change to a work order is a transition with a permission check, a state
    check and a recorded actor, and a free-form admin form is a way to make
    one without any of the three. Verified work orders would refuse the write
    anyway (models.WorkOrderSealedError); the others would accept an edit that
    no audit trail explains.
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
