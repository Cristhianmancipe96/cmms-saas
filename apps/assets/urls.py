from django.urls import path

from apps.assets import views

urlpatterns = [
    path("categorias/", views.AssetCategoryListView.as_view(), name="assetcategory_list"),
    path("categorias/nueva/", views.category_create, name="assetcategory_create"),
    path("equipos/", views.AssetListView.as_view(), name="asset_list"),
    path("equipos/nuevo/", views.asset_create, name="asset_create"),
    path("equipos/specs-fila/", views.asset_spec_row, name="asset_spec_row"),
    path(
        "equipos/documentos/<int:pk>/",
        views.asset_document_download,
        name="assetdocument_download",
    ),
    path("equipos/<int:pk>/", views.AssetDetailView.as_view(), name="asset_detail"),
    path("equipos/<int:pk>/editar/", views.asset_update, name="asset_update"),
    path("equipos/<int:pk>/dar-de-baja/", views.asset_baja, name="asset_baja"),
    path("equipos/<int:pk>/eliminar/", views.asset_delete, name="asset_delete"),
    path("equipos/<int:pk>/foto/", views.asset_photo_download, name="asset_photo_download"),
    path(
        "equipos/<int:pk>/documentos/subir/",
        views.asset_document_upload,
        name="assetdocument_upload",
    ),
]
