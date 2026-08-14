from django.urls import path

from apps.maintenance import views

urlpatterns = [
    path("planes/", views.MaintenancePlanListView.as_view(), name="maintenanceplan_list"),
    path("planes/<int:pk>/", views.plan_detail, name="maintenanceplan_detail"),
    path("planes/<int:pk>/editar/", views.plan_update, name="maintenanceplan_update"),
    path("planes/<int:pk>/estado/", views.plan_toggle_active, name="maintenanceplan_toggle"),
    path("planes/<int:pk>/eliminar/", views.plan_delete, name="maintenanceplan_delete"),
    path(
        "equipos/<int:asset_pk>/planes/nuevo/",
        views.plan_create,
        name="maintenanceplan_create",
    ),
    path(
        "equipos/<int:asset_pk>/horometro/",
        views.meter_reading_create,
        name="meterreading_create",
    ),
]
