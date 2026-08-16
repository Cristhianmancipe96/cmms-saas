from django.urls import path

from apps.kpis import views

urlpatterns = [
    path("tablero/", views.dashboard, name="kpi_dashboard"),
]
