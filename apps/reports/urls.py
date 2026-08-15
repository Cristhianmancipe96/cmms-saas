from django.urls import path

from apps.reports import views

urlpatterns = [
    path(
        "equipos/<int:pk>/hoja-de-vida.pdf",
        views.asset_record_pdf,
        name="asset_record_pdf",
    ),
    path(
        "equipos/<int:pk>/hoja-de-vida/enviar/",
        views.asset_record_send,
        name="asset_record_send",
    ),
    path(
        "ordenes/<int:pk>/informe.pdf",
        views.work_order_report_pdf,
        name="workorder_report_pdf",
    ),
    path(
        "ordenes/<int:pk>/informe/enviar/",
        views.work_order_report_send,
        name="workorder_report_send",
    ),
]
