from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.accounts.models import User
from apps.assets.models import AssetCategory
from apps.checklists import services
from apps.checklists.forms import ChecklistTemplateForm, ChecklistTemplateItemForm
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem
from apps.core.rbac import RoleRequiredMixin, deny, role_required

ALL_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN, User.Role.STAFF)
MANAGER_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR)


class ChecklistTemplateListView(RoleRequiredMixin, ListView):
    allowed_roles = ALL_ROLES
    model = ChecklistTemplate
    template_name = "checklists/template_list.html"
    context_object_name = "templates"

    def get_queryset(self):
        queryset = ChecklistTemplate.objects.select_related("category", "parent").all()
        params = self.request.GET
        if category_id := params.get("category"):
            queryset = queryset.filter(category_id=category_id)
        if estado := params.get("estado"):
            queryset = queryset.filter(is_active=(estado == "activa"))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = AssetCategory.objects.all()
        context["filters"] = self.request.GET
        return context


@role_required(*MANAGER_ROLES)
def checklist_template_create(request):
    company = request.user.company
    if company is None:
        return deny(request)

    if request.method == "POST":
        form = ChecklistTemplateForm(request.POST, company=company)
        if form.is_valid():
            template = form.save(commit=False)
            template.company = company
            template.version = 1
            template.is_active = True
            template.save()
            messages.success(request, f"Plantilla {template.name} creada.")
            return redirect("checklisttemplate_detail", template.pk)
    else:
        form = ChecklistTemplateForm(company=company)
    return render(request, "checklists/template_form.html", {"form": form})


@role_required(*ALL_ROLES)
def checklist_template_detail(request, pk):
    template = get_object_or_404(
        ChecklistTemplate.objects.select_related("category", "parent"), pk=pk
    )
    items = template.items.order_by("order")
    can_manage = request.user.is_platform_admin or request.user.role in MANAGER_ROLES
    return render(
        request,
        "checklists/template_detail.html",
        {"template": template, "items": items, "can_manage": can_manage},
    )


@role_required(*MANAGER_ROLES)
def checklist_item_create(request, pk):
    template = get_object_or_404(ChecklistTemplate, pk=pk)
    if request.method == "POST":
        form = ChecklistTemplateItemForm(request.POST)
        if form.is_valid():
            target, _item = services.add_item(template, **form.cleaned_data)
            messages.success(request, "Ítem agregado.")
            return redirect("checklisttemplate_detail", target.pk)
    else:
        form = ChecklistTemplateItemForm()
    return render(
        request,
        "checklists/item_form.html",
        {"form": form, "template": template, "is_create": True},
    )


@role_required(*MANAGER_ROLES)
def checklist_item_update(request, pk, item_pk):
    template = get_object_or_404(ChecklistTemplate, pk=pk)
    item = get_object_or_404(ChecklistTemplateItem, pk=item_pk, template=template)
    if request.method == "POST":
        # instance=item only feeds initial values / validation — form.save()
        # is never called. The actual write always goes through
        # services.update_item, so a locked template forks instead of
        # mutating this row in place.
        form = ChecklistTemplateItemForm(request.POST, instance=item)
        if form.is_valid():
            target, _item = services.update_item(template, item, **form.cleaned_data)
            messages.success(request, "Ítem actualizado.")
            return redirect("checklisttemplate_detail", target.pk)
    else:
        form = ChecklistTemplateItemForm(instance=item)
    return render(
        request,
        "checklists/item_form.html",
        {"form": form, "template": template, "item": item, "is_create": False},
    )


@role_required(*MANAGER_ROLES)
@require_POST
def checklist_item_move_up(request, pk, item_pk):
    template = get_object_or_404(ChecklistTemplate, pk=pk)
    item = get_object_or_404(ChecklistTemplateItem, pk=item_pk, template=template)
    target = services.move_item(template, item, direction=-1)
    return redirect("checklisttemplate_detail", target.pk)


@role_required(*MANAGER_ROLES)
@require_POST
def checklist_item_move_down(request, pk, item_pk):
    template = get_object_or_404(ChecklistTemplate, pk=pk)
    item = get_object_or_404(ChecklistTemplateItem, pk=item_pk, template=template)
    target = services.move_item(template, item, direction=1)
    return redirect("checklisttemplate_detail", target.pk)


@role_required(*MANAGER_ROLES)
@require_POST
def checklist_template_duplicate(request, pk):
    template = get_object_or_404(ChecklistTemplate, pk=pk)
    new_template = services.duplicate_template(template)
    messages.success(request, f"Plantilla duplicada como {new_template.name}.")
    return redirect("checklisttemplate_detail", new_template.pk)


@role_required(*MANAGER_ROLES)
@require_POST
def checklist_template_deactivate(request, pk):
    template = get_object_or_404(ChecklistTemplate, pk=pk)
    services.deactivate_template(template)
    messages.success(request, f"Plantilla {template.name} desactivada.")
    return redirect("checklisttemplate_detail", template.pk)
