from django.urls import path

from apps.audit import views

urlpatterns = [
    path("auditoria/", views.AuditLogListView.as_view(), name="auditlog_list"),
]
