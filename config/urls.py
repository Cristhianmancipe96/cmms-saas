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
]
