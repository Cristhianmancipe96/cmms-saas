"""
URL configuration for the cmms-saas project.
"""

from django.contrib import admin
from django.urls import include, path

from apps.core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", core_views.home, name="home"),
    path("", include("apps.accounts.urls")),
    path("", include("apps.assets.urls")),
    path("", include("apps.checklists.urls")),
    path("", include("apps.maintenance.urls")),
    path("", include("apps.workorders.urls")),
    path("", include("apps.reports.urls")),
]
