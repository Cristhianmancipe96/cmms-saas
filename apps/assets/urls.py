from django.urls import path

from apps.assets import views

urlpatterns = [
    # Brief 06. Short and slash-less on purpose: this string is printed onto a
    # sticker and re-typed by hand when a label is too dirty to scan, and every
    # character it does not have is one that cannot be mistyped. No trailing
    # slash also means no APPEND_SLASH redirect — one fewer round trip on the
    # phone of someone standing in front of a stopped machine.
    path("e/<uuid:qr_uuid>", views.asset_scan, name="asset_scan"),
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
    path("equipos/<int:pk>/etiqueta/", views.asset_label, name="asset_label"),
    path(
        "equipos/<int:pk>/documentos/subir/",
        views.asset_document_upload,
        name="assetdocument_upload",
    ),
]
