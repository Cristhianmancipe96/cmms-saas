from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.accounts.models import Company, Site, Subscription, User


class SubscriptionInline(admin.StackedInline):
    model = Subscription
    can_delete = False


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "nit", "is_active", "created_at"]
    search_fields = ["name", "nit"]
    inlines = [SubscriptionInline]


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "address"]
    list_filter = ["company"]
    search_fields = ["name"]

    def get_queryset(self, request):
        # .unscoped() is the sanctioned cross-company bypass (apps/core/tenancy.py)
        # and stays reserved for is_platform_admin — Django admin access alone
        # (is_staff) isn't the same authority. A full is_platform_admin gate on
        # /admin/ itself is brief 10's job; this only stops the queryset leak.
        if request.user.is_platform_admin:
            return self.model.objects.unscoped()
        return super().get_queryset(request)


@admin.register(User)
class CompanyUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "CMMS",
            {
                "fields": (
                    "company",
                    "role",
                    "whatsapp_phone",
                    "is_platform_admin",
                )
            },
        ),
    )
    list_display = ["username", "email", "company", "role", "is_platform_admin", "is_active"]
    list_filter = ["company", "role", "is_platform_admin", "is_active"]

    def get_queryset(self, request):
        # User has no CompanyScopedManager (auth must resolve before a company
        # context exists), so Django admin's default queryset is unscoped by
        # construction. Narrow it explicitly here for the same reason as
        # SiteAdmin above.
        queryset = super().get_queryset(request)
        if request.user.is_platform_admin:
            return queryset
        return queryset.filter(company=request.user.company)
