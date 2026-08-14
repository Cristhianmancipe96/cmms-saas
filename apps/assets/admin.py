from django.contrib import admin

from apps.assets.models import Asset, AssetCategory, AssetDocument


class AssetDocumentInline(admin.TabularInline):
    model = AssetDocument
    extra = 0
    fields = ["kind", "file", "name", "uploaded_by", "uploaded_at"]
    readonly_fields = ["uploaded_at"]


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "company"]
    list_filter = ["company"]
    search_fields = ["name"]

    def get_queryset(self, request):
        if request.user.is_platform_admin:
            return self.model.objects.unscoped()
        return super().get_queryset(request)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "company", "site", "status", "criticality"]
    list_filter = ["company", "status", "criticality"]
    search_fields = ["code", "name", "serial_number"]
    inlines = [AssetDocumentInline]

    def get_queryset(self, request):
        if request.user.is_platform_admin:
            return self.model.objects.unscoped()
        return super().get_queryset(request)
