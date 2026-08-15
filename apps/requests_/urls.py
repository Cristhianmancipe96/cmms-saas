from django.urls import path

from apps.requests_ import views

urlpatterns = [
    path(
        "solicitudes/",
        views.MaintenanceRequestListView.as_view(),
        name="maintenancerequest_list",
    ),
    path("solicitudes/<int:pk>/", views.request_detail, name="maintenancerequest_detail"),
    path(
        "solicitudes/<int:pk>/convertir/",
        views.request_convert,
        name="maintenancerequest_convert",
    ),
    path(
        "solicitudes/<int:pk>/rechazar/",
        views.request_reject,
        name="maintenancerequest_reject",
    ),
    path(
        "solicitudes/<int:pk>/foto/",
        views.request_photo_download,
        name="maintenancerequest_photo",
    ),
    path(
        "equipos/<int:asset_pk>/reportar-falla/",
        views.request_create,
        name="maintenancerequest_create",
    ),
]
