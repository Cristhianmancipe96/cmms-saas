from django.contrib import admin

from apps.maintenance.models import MaintenancePlan, MeterReading


@admin.register(MaintenancePlan)
class MaintenancePlanAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "asset", "frequency_type", "next_due_date", "is_active"]
    list_filter = ["company", "is_active", "frequency_type", "kind"]
    search_fields = ["name"]
    autocomplete_fields = ["asset"]

    def get_queryset(self, request):
        if request.user.is_platform_admin:
            return self.model.objects.unscoped()
        return super().get_queryset(request)


@admin.register(MeterReading)
class MeterReadingAdmin(admin.ModelAdmin):
    list_display = ["asset", "reading_hours", "read_at", "source", "recorded_by"]
    list_filter = ["company", "source"]
    autocomplete_fields = ["asset"]

    def get_queryset(self, request):
        if request.user.is_platform_admin:
            return self.model.objects.unscoped()
        return super().get_queryset(request)
