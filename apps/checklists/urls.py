from django.urls import path

from apps.checklists import views

urlpatterns = [
    path("checklists/", views.ChecklistTemplateListView.as_view(), name="checklisttemplate_list"),
    path("checklists/nueva/", views.checklist_template_create, name="checklisttemplate_create"),
    path("checklists/<int:pk>/", views.checklist_template_detail, name="checklisttemplate_detail"),
    path(
        "checklists/<int:pk>/duplicar/",
        views.checklist_template_duplicate,
        name="checklisttemplate_duplicate",
    ),
    path(
        "checklists/<int:pk>/desactivar/",
        views.checklist_template_deactivate,
        name="checklisttemplate_deactivate",
    ),
    path(
        "checklists/<int:pk>/items/nuevo/",
        views.checklist_item_create,
        name="checklistitem_create",
    ),
    path(
        "checklists/<int:pk>/items/<int:item_pk>/editar/",
        views.checklist_item_update,
        name="checklistitem_update",
    ),
    path(
        "checklists/<int:pk>/items/<int:item_pk>/subir/",
        views.checklist_item_move_up,
        name="checklistitem_move_up",
    ),
    path(
        "checklists/<int:pk>/items/<int:item_pk>/bajar/",
        views.checklist_item_move_down,
        name="checklistitem_move_down",
    ),
]
