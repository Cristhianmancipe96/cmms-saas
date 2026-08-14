from django.contrib import messages
from django.db.models import F, ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.accounts.models import User
from apps.assets.models import Asset
from apps.core.rbac import RoleRequiredMixin, deny, role_required
from apps.maintenance import services
from apps.maintenance.forms import MaintenancePlanForm, MeterReadingForm
from apps.maintenance.models import MaintenancePlan, MeterReading

ALL_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN, User.Role.STAFF)
MANAGER_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR)
# Recording an hour meter is shop-floor work, so technicians do it. `staff`
# is the office role (invoices, paperwork) and has no business writing
# machine telemetry.
READING_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN)

RECENT_READINGS = 5

PLAN_NOT_DELETABLE = (
    "No se puede eliminar un plan que ya generó órdenes de trabajo. "
    "Desactívalo en su lugar."
)


def _can_manage(user) -> bool:
    return user.is_platform_admin or user.role in MANAGER_ROLES


# --- Plans ------------------------------------------------------------------


class MaintenancePlanListView(RoleRequiredMixin, ListView):
    """Company-wide plan list: overdue first, then whatever is due soonest.

    `get_queryset` returns an annotated *list* rather than a queryset. Due
    state for a meter plan is a comparison against that asset's newest
    reading, which SQL here cannot express without a correlated subquery per
    row; `annotate_due_state` resolves the whole page in one extra aggregate
    query instead. Paginator handles lists natively, and a single company's
    plan count is in the tens, not the millions.
    """

    allowed_roles = ALL_ROLES
    template_name = "maintenance/plan_list.html"
    context_object_name = "plans"
    paginate_by = 25

    def get_queryset(self):
        queryset = MaintenancePlan.objects.select_related(
            "asset", "asset__site", "default_assignee"
        ).order_by(F("next_due_date").asc(nulls_last=True), "name")

        estado = self.request.GET.get("estado", "")
        if estado == "activos":
            queryset = queryset.filter(is_active=True)
        elif estado == "inactivos":
            queryset = queryset.filter(is_active=False)

        plans = services.annotate_due_state(queryset)
        if estado == "vencidos":
            plans = [plan for plan in plans if plan.due_state == "vencido"]
        return plans

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filters"] = self.request.GET
        # self.object_list is the whole filtered set; context["plans"] is only
        # the current page. "How many are overdue" is a question about the
        # company, not about page 2, so count the former.
        context["overdue_count"] = sum(
            1 for plan in self.object_list if plan.due_state == "vencido"
        )
        context["can_manage"] = _can_manage(self.request.user)
        context["is_filtered"] = bool(self.request.GET.get("estado"))
        return context


@role_required(*ALL_ROLES)
def plan_detail(request, pk):
    plan = get_object_or_404(
        MaintenancePlan.objects.select_related(
            "asset", "asset__site", "checklist_template", "default_assignee"
        ),
        pk=pk,
    )
    services.annotate_due_state([plan])
    return render(
        request,
        "maintenance/plan_detail.html",
        {
            "plan": plan,
            "can_manage": _can_manage(request.user),
            "resolved_template": services.resolve_checklist_template(plan),
            "latest_hours": services.latest_reading_hours(plan.asset_id),
        },
    )


@role_required(*MANAGER_ROLES)
def plan_create(request, asset_pk):
    company = request.user.company
    if company is None:
        return deny(request)
    asset = get_object_or_404(Asset, pk=asset_pk)

    if request.method == "POST":
        form = MaintenancePlanForm(request.POST, company=company)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.company = company
            plan.asset = asset
            if not plan.is_calendar:
                # Seed the meter baseline with what the machine reads today,
                # otherwise a plan added to an asset already at 5.000 h would
                # generate a work order on the very next scheduler run.
                plan.hours_at_last_generated_wo = services.latest_reading_hours(asset.pk) or 0
            plan.save()
            messages.success(request, f"Plan {plan.name} creado.")
            return redirect("maintenanceplan_detail", plan.pk)
    else:
        form = MaintenancePlanForm(company=company)
    return render(
        request,
        "maintenance/plan_form.html",
        {"form": form, "asset": asset, "is_create": True},
    )


@role_required(*MANAGER_ROLES)
def plan_update(request, pk):
    company = request.user.company
    plan = get_object_or_404(MaintenancePlan.objects.select_related("asset"), pk=pk)

    was_calendar = plan.is_calendar

    if request.method == "POST":
        form = MaintenancePlanForm(request.POST, instance=plan, company=company)
        if form.is_valid():
            plan = form.save(commit=False)
            if was_calendar and not plan.is_calendar:
                # Switching a calendar plan over to the hour meter starts the
                # count now, not at zero — otherwise the first scheduler run
                # would read "5.000 h elapsed" and fire immediately. Switching
                # between two meter plans must NOT reset it: that would throw
                # away the progress since the last generated work order.
                plan.hours_at_last_generated_wo = services.latest_reading_hours(plan.asset_id) or 0
            plan.save()
            messages.success(request, f"Plan {plan.name} actualizado.")
            return redirect("maintenanceplan_detail", plan.pk)
    else:
        form = MaintenancePlanForm(instance=plan, company=company)
    return render(
        request,
        "maintenance/plan_form.html",
        {"form": form, "asset": plan.asset, "plan": plan, "is_create": False},
    )


@role_required(*MANAGER_ROLES)
@require_POST
def plan_toggle_active(request, pk):
    plan = get_object_or_404(MaintenancePlan, pk=pk)
    plan.is_active = not plan.is_active
    plan.save(update_fields=["is_active", "updated_at"])
    if plan.is_active:
        messages.success(request, f"Plan {plan.name} activado.")
    else:
        messages.success(request, f"Plan {plan.name} desactivado. No generará más OTs.")
    return redirect("maintenanceplan_detail", plan.pk)


@role_required(*MANAGER_ROLES)
def plan_delete(request, pk):
    plan = get_object_or_404(MaintenancePlan.objects.select_related("asset"), pk=pk)
    if request.method == "POST":
        asset_pk = plan.asset_id
        try:
            plan.delete()
        except ProtectedError:
            # PROTECT on WorkOrder.plan: work orders are audit evidence and
            # keep their link to the plan that scheduled them.
            messages.error(request, PLAN_NOT_DELETABLE)
            return redirect("maintenanceplan_detail", plan.pk)
        messages.success(request, f"Plan {plan.name} eliminado.")
        return redirect("asset_detail", asset_pk)
    return render(request, "maintenance/plan_delete_confirm.html", {"plan": plan})


# --- Meter readings ---------------------------------------------------------


def meter_panel_context(asset, *, user, form=None) -> dict:
    """Everything the horómetro panel renders.

    Public on purpose: the asset detail page (apps/assets) and the HTMX
    response that replaces the panel after a reading is saved must build the
    identical context, permission decision included, or the two renders of
    the same component would drift apart.
    """
    return {
        "asset": asset,
        "latest_hours": services.latest_reading_hours(asset.pk),
        "readings": MeterReading.objects.select_related("recorded_by").filter(asset=asset)[
            :RECENT_READINGS
        ],
        "meter_form": form if form is not None else MeterReadingForm(asset=asset),
        "can_record_reading": user.is_platform_admin or user.role in READING_ROLES,
    }


@role_required(*READING_ROLES)
@require_POST
def meter_reading_create(request, asset_pk):
    asset = get_object_or_404(Asset, pk=asset_pk)
    form = MeterReadingForm(request.POST, asset=asset)
    saved = False
    if form.is_valid():
        reading = form.save(commit=False)
        reading.company = asset.company
        reading.asset = asset
        reading.source = MeterReading.Source.MANUAL
        reading.recorded_by = request.user
        reading.save()
        saved = True
        form = MeterReadingForm(asset=asset)

    context = meter_panel_context(asset, user=request.user, form=form)
    context["just_saved"] = saved

    if request.headers.get("HX-Request"):
        return render(request, "maintenance/_meter_panel.html", context)

    if saved:
        messages.success(request, "Lectura registrada.")
    else:
        for error in form.errors.get("reading_hours", []):
            messages.error(request, error)
    return redirect("asset_detail", asset.pk)
