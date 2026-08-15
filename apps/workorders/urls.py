from django.urls import path

from apps.workorders import views

urlpatterns = [
    path("ordenes/", views.WorkOrderListView.as_view(), name="workorder_list"),
    path("ordenes/mias/", views.my_work_orders, name="workorder_mine"),
    path("ordenes/<int:pk>/", views.work_order_detail, name="workorder_detail"),
    path("ordenes/<int:pk>/ejecutar/", views.work_order_execute, name="workorder_execute"),
    path("ordenes/<int:pk>/asignar/", views.work_order_assign, name="workorder_assign"),
    path("ordenes/<int:pk>/iniciar/", views.work_order_start, name="workorder_start"),
    path("ordenes/<int:pk>/terminar/", views.work_order_complete, name="workorder_complete"),
    path("ordenes/<int:pk>/verificar/", views.work_order_verify, name="workorder_verify"),
    path("ordenes/<int:pk>/cancelar/", views.work_order_cancel, name="workorder_cancel"),
    path(
        "ordenes/<int:pk>/items/<int:item_pk>/",
        views.work_order_item_save,
        name="workorder_item_save",
    ),
    path("ordenes/<int:pk>/fotos/", views.work_order_photo_upload, name="workorder_photo_upload"),
    path(
        "ordenes/<int:pk>/fotos/<int:photo_pk>/imagen/",
        views.work_order_photo_download,
        name="workorder_photo_download",
    ),
    path(
        "equipos/<int:asset_pk>/ordenes/nueva/",
        views.corrective_create,
        name="workorder_corrective_create",
    ),
]
