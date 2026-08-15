"""Work-order screens.

Three audiences, three shapes:

- the **technician** gets «Mis OTs» and the execution screen, both designed
  for a phone held in one hand on a plant floor;
- the **supervisor** gets a filterable company-wide list and the detail
  screen, where assigning, verifying and cancelling live;
- everyone gets the detail screen read-only, because a work order is the
  record other people cite.

Every view resolves its work order through the scoped manager, so a URL from
another company 404s rather than 403s — an existence oracle is a leak too.
Permission decisions beyond "which role" (is this *your* work order?) come
from `services.available_actions`, never from a second copy of the rules in a
template.
"""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.accounts.models import User
from apps.assets.models import Asset
from apps.assets.views import serve_file
from apps.core.rbac import RoleRequiredMixin, deny, role_required
from apps.workorders import services
from apps.workorders.forms import (
    CorrectiveWorkOrderForm,
    WorkOrderAssignForm,
    WorkOrderCancelForm,
    WorkOrderCompleteForm,
    WorkOrderPhotoForm,
)
from apps.workorders.models import WorkOrder, WorkOrderChecklistItem, WorkOrderPhoto

ALL_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN, User.Role.STAFF)


def _querystring_without_page(params) -> str:
    """Carry the active filters across pagination links (and nothing else)."""
    kept = params.copy()
    kept.pop("page", None)
    encoded = kept.urlencode()
    return f"{encoded}&" if encoded else ""


def _base_queryset():
    return WorkOrder.objects.select_related(
        "asset",
        "asset__site",
        "assigned_to",
        "plan",
        "completed_by",
        "verified_by",
        # The detail screen names the snapshotted version ("copiado de X v2"),
        # and the list rows render the asset and assignee — all FKs, all
        # fetched up front so a page of 25 rows is one query, not 76.
        "checklist_template",
    )


def _may_execute(work_order: WorkOrder, user) -> bool:
    """Who may open the execution screen (acceptance criterion 7).

    The assignee, because it is their work; supervisors and admins, because
    they answer for it. Another technician in the same company may not — a
    checklist is signed work, and a screen that offers to fill in someone
    else's is an invitation to do exactly that.
    """
    return services.is_manager(user) or work_order.assigned_to_id == user.pk


# --- Lists ------------------------------------------------------------------


class WorkOrderListView(RoleRequiredMixin, ListView):
    """The supervisor's queue: everything, filterable, overdue first."""

    allowed_roles = ALL_ROLES
    template_name = "workorders/work_order_list.html"
    context_object_name = "work_orders"
    paginate_by = 25

    def get_queryset(self):
        queryset = _base_queryset().order_by(F("due_date").asc(nulls_last=True), "-id")
        params = self.request.GET
        if status := params.get("estado"):
            queryset = queryset.filter(status=status)
        if asset_id := params.get("equipo"):
            queryset = queryset.filter(asset_id=asset_id)
        if technician_id := params.get("tecnico"):
            queryset = queryset.filter(assigned_to_id=technician_id)
        if wo_type := params.get("tipo"):
            queryset = queryset.filter(type=wo_type)
        if params.get("vencidas"):
            queryset = queryset.filter(
                due_date__lt=timezone.localdate(), status__in=WorkOrder.OPEN_STATUSES
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        context["today"] = today
        context["work_orders"] = services.annotate_overdue(context["work_orders"], today=today)
        # self.object_list is the whole filtered set; context["work_orders"] is
        # only this page. "How many are overdue" is a question about the
        # company, not about page 2.
        context["overdue_count"] = self.object_list.filter(
            due_date__lt=today, status__in=WorkOrder.OPEN_STATUSES
        ).count()
        context["filters"] = self.request.GET
        context["querystring"] = _querystring_without_page(self.request.GET)
        context["is_filtered"] = any(self.request.GET.values())
        context["assets"] = Asset.objects.order_by("name")
        context["technicians"] = User.objects.filter(
            role__in=services.ASSIGNABLE_ROLES, is_active=True
        ).order_by("username")
        context["status_choices"] = WorkOrder.Status.choices
        context["type_choices"] = WorkOrder.Type.choices
        context["can_report"] = services.may_report_failure(self.request.user)
        return context


@role_required(*ALL_ROLES)
def my_work_orders(request):
    """The technician's home screen: what is on me, worst first.

    Three buckets rather than one list, because the question a technician
    actually asks at 7am is "what am I late on?" and a single date-sorted list
    makes them work that out for themselves.
    """
    today = timezone.localdate()
    mine = (
        _base_queryset()
        .filter(assigned_to=request.user, status__in=WorkOrder.OPEN_STATUSES)
        .order_by(F("due_date").asc(nulls_last=True), "-id")
    )
    rows = services.annotate_overdue(mine, today=today)
    overdue = [wo for wo in rows if wo.due_date is not None and wo.due_date < today]
    due_today = [wo for wo in rows if wo.due_date == today]
    upcoming = [wo for wo in rows if wo.due_date is None or wo.due_date > today]
    return render(
        request,
        "workorders/my_work_orders.html",
        {
            "today": today,
            "overdue": overdue,
            "due_today": due_today,
            "upcoming": upcoming,
            "total": len(overdue) + len(due_today) + len(upcoming),
        },
    )


# --- Detail -----------------------------------------------------------------


def _timeline(work_order: WorkOrder) -> list[dict]:
    """Who moved this work order, and when.

    Derived from the work order's own timestamps rather than from an event
    table: brief 08 introduces the audit log, and inventing half of it here
    would leave two sources of truth to reconcile later. Everything shown is
    a stored fact, not a reconstruction.
    """
    events = [
        {"label": "Creada", "when": work_order.created_at, "who": None, "note": ""},
    ]
    if work_order.started_at:
        events.append(
            {
                "label": "Iniciada",
                "when": work_order.started_at,
                "who": work_order.assigned_to,
                "note": "",
            }
        )
    if work_order.finished_at:
        events.append(
            {
                "label": "Terminada",
                "when": work_order.finished_at,
                "who": work_order.completed_by,
                "note": "",
            }
        )
    if work_order.verified_at:
        events.append(
            {
                "label": "Verificada",
                "when": work_order.verified_at,
                "who": work_order.verified_by,
                "note": "",
            }
        )
    if work_order.status == WorkOrder.Status.CANCELADA:
        events.append(
            {
                "label": "Cancelada",
                "when": work_order.updated_at,
                "who": None,
                "note": work_order.cancel_reason,
            }
        )
    return events


@role_required(*ALL_ROLES)
def work_order_detail(request, pk):
    work_order = get_object_or_404(_base_queryset(), pk=pk)
    services.annotate_overdue([work_order])
    actions = services.available_actions(work_order, request.user)
    return render(
        request,
        "workorders/work_order_detail.html",
        {
            "wo": work_order,
            "today": timezone.localdate(),
            "items": services.checklist_items(work_order),
            "photos": services.photos(work_order),
            "timeline": _timeline(work_order),
            "actions": actions,
            "assign_form": (
                WorkOrderAssignForm(company=work_order.company)
                if services.ASSIGN in actions
                else None
            ),
            "can_execute": _may_execute(work_order, request.user),
            "pending_required": len(services.pending_required_items(work_order)),
            # Brief 07: the report is a document about work that happened, so
            # it appears only once the work order says it did.
            "report_available": work_order.status in WorkOrder.DONE_STATUSES,
            "can_email_report": services.is_manager(request.user),
        },
    )


# --- Execution (the phone screen) -------------------------------------------


def _progress_context(items: list[WorkOrderChecklistItem]) -> dict:
    """The numbers `_checklist_progress.html` renders — built in one place so
    the full page and the out-of-band HTMX fragment cannot disagree."""
    answered = sum(1 for item in items if item.is_answered)
    total = len(items)
    return {
        "items_total": total,
        "answered_count": answered,
        "answered_percent": round(answered * 100 / total) if total else 0,
        "pending_required": sum(1 for item in items if item.required and not item.is_answered),
    }


def _execution_context(request, work_order: WorkOrder, *, complete_form=None) -> dict:
    items = list(services.checklist_items(work_order))
    is_assignee = work_order.assigned_to_id == request.user.pk
    tracks_meter = services.asset_tracks_meter(work_order.asset_id)
    return {
        "wo": work_order,
        "items": items,
        "photos": services.photos(work_order),
        "photo_form": WorkOrderPhotoForm(),
        "complete_form": complete_form
        if complete_form is not None
        else WorkOrderCompleteForm(tracks_meter=tracks_meter),
        "is_assignee": is_assignee,
        # The screen renders for supervisors too (read-only) and for the
        # assignee before they press «Iniciar»: one flag decides every disabled
        # attribute instead of repeating the condition per widget.
        "can_answer": is_assignee and work_order.status == WorkOrder.Status.EN_PROGRESO,
        "actions": services.available_actions(work_order, request.user),
        **_progress_context(items),
    }


@role_required(*ALL_ROLES)
def work_order_execute(request, pk):
    work_order = get_object_or_404(_base_queryset(), pk=pk)
    if not _may_execute(work_order, request.user):
        return deny(request)
    return render(
        request,
        "workorders/work_order_execute.html",
        _execution_context(request, work_order),
    )


@role_required(*ALL_ROLES)
@require_POST
def work_order_item_save(request, pk, item_pk):
    """One checklist answer, saved on its own (HTMX).

    Per item, not per form: the network on a plant floor drops, and the work
    already recorded must survive it. The response re-renders that single row
    plus an out-of-band progress line, so the "faltan N ítems" counter and the
    row can never disagree.
    """
    work_order = get_object_or_404(WorkOrder.objects.all(), pk=pk)
    # The service refuses the write anyway, but the response renders the
    # checklist row — and someone who may not open the execution screen must
    # not be able to read it one row at a time through a failed POST either.
    if not _may_execute(work_order, request.user):
        return deny(request)
    item = get_object_or_404(
        WorkOrderChecklistItem.objects.all(), pk=item_pk, work_order=work_order
    )

    error = None
    try:
        services.record_item_result(
            work_order,
            item,
            user=request.user,
            result=request.POST.get("result", ""),
            numeric_value=_decimal_or_none(request.POST.get("numeric_value")),
            note=request.POST.get("note", ""),
        )
    except services.WorkOrderError as service_error:
        error = str(service_error)

    if request.headers.get("HX-Request"):
        # Re-read the whole checklist rather than trusting the in-memory item:
        # the row that goes back must show what the database now holds, and
        # the progress line is computed from the same read.
        items = list(services.checklist_items(work_order))
        return render(
            request,
            "workorders/_checklist_item_response.html",
            {
                "wo": work_order,
                "item": next(row for row in items if row.pk == item.pk),
                "error": error,
                "can_answer": (
                    work_order.assigned_to_id == request.user.pk
                    and work_order.status == WorkOrder.Status.EN_PROGRESO
                ),
                **_progress_context(items),
            },
        )

    if error:
        messages.error(request, error)
    return redirect("workorder_execute", work_order.pk)


def _decimal_or_none(raw):
    """A number typed with gloves on. Accepts "12,5" as well as "12.5" —
    es-CO keyboards put a comma there and rejecting it teaches nothing."""
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


@role_required(*ALL_ROLES)
@require_POST
def work_order_photo_upload(request, pk):
    work_order = get_object_or_404(WorkOrder.objects.all(), pk=pk)
    # Evidence is attached by whoever is doing the work, while they are doing
    # it. A photo added afterwards by someone else is a different claim.
    if work_order.assigned_to_id != request.user.pk:
        return deny(request)
    if work_order.status != WorkOrder.Status.EN_PROGRESO:
        messages.error(request, "Solo se pueden adjuntar fotos con la OT en progreso.")
        return redirect("workorder_execute", work_order.pk)

    form = WorkOrderPhotoForm(request.POST, request.FILES)
    if form.is_valid():
        photo = form.save(commit=False)
        photo.company_id = work_order.company_id
        photo.work_order = work_order
        photo.taken_by = request.user
        photo.save()
        messages.success(request, "Foto adjuntada.")
    else:
        for error_list in form.errors.values():
            for error in error_list:
                messages.error(request, error)
    return redirect("workorder_execute", work_order.pk)


@role_required(*ALL_ROLES)
def work_order_photo_download(request, pk, photo_pk):
    """Photos are tenant data: served through here, never as a public
    /media/ URL (CLAUDE.md security rules)."""
    work_order = get_object_or_404(WorkOrder.objects.all(), pk=pk)
    photo = get_object_or_404(WorkOrderPhoto.objects.all(), pk=photo_pk, work_order=work_order)
    if not photo.image:
        raise Http404
    return serve_file(photo.image)


# --- Transitions ------------------------------------------------------------


def _run(request, work_order: WorkOrder, action: str, **payload) -> bool:
    """Apply a transition and turn any refusal into a Spanish message."""
    try:
        services.transition(work_order, action, request.user, **payload)
    except services.WorkOrderError as error:
        messages.error(request, str(error))
        return False
    return True


@role_required(*ALL_ROLES)
@require_POST
def work_order_assign(request, pk):
    work_order = get_object_or_404(WorkOrder.objects.all(), pk=pk)
    form = WorkOrderAssignForm(request.POST, company=work_order.company)
    if not form.is_valid():
        messages.error(request, "Elige a quién se le asigna la OT.")
    elif _run(request, work_order, services.ASSIGN, assignee=form.cleaned_data["assignee"]):
        messages.success(request, f"OT asignada a {form.cleaned_data['assignee']}.")
    return redirect("workorder_detail", work_order.pk)


@role_required(*ALL_ROLES)
@require_POST
def work_order_start(request, pk):
    work_order = get_object_or_404(WorkOrder.objects.all(), pk=pk)
    if _run(request, work_order, services.START):
        messages.success(request, "OT iniciada. Llena el checklist a medida que avances.")
        return redirect("workorder_execute", work_order.pk)
    return redirect("workorder_detail", work_order.pk)


@role_required(*ALL_ROLES)
@require_POST
def work_order_complete(request, pk):
    work_order = get_object_or_404(_base_queryset(), pk=pk)
    # Both failure paths below re-render the execution screen, so the same
    # gate that guards a GET has to guard this POST.
    if not _may_execute(work_order, request.user):
        return deny(request)
    form = WorkOrderCompleteForm(
        request.POST, tracks_meter=services.asset_tracks_meter(work_order.asset_id)
    )
    if not form.is_valid():
        for error_list in form.errors.values():
            for error in error_list:
                messages.error(request, error)
        return render(
            request,
            "workorders/work_order_execute.html",
            _execution_context(request, work_order, complete_form=form),
        )

    if _run(request, work_order, services.COMPLETE, **form.payload()):
        messages.success(request, "OT terminada. Queda pendiente la verificación del supervisor.")
        return redirect("workorder_detail", work_order.pk)
    return render(
        request,
        "workorders/work_order_execute.html",
        _execution_context(request, work_order, complete_form=form),
    )


@role_required(*ALL_ROLES)
def work_order_verify(request, pk):
    """Sealing a work order is irreversible, so it gets its own screen.

    A one-tap button next to "cancelar" would make the most consequential
    action on the object the easiest to hit by accident.
    """
    work_order = get_object_or_404(_base_queryset(), pk=pk)
    if request.method == "POST":
        if _run(request, work_order, services.VERIFY):
            messages.success(request, "OT verificada. Queda sellada como evidencia.")
            return redirect("workorder_detail", work_order.pk)
        return redirect("workorder_detail", work_order.pk)
    if services.VERIFY not in services.available_actions(work_order, request.user):
        return deny(request)
    return render(
        request,
        "workorders/work_order_verify_confirm.html",
        {
            "wo": work_order,
            "items": services.checklist_items(work_order),
            "photos": services.photos(work_order),
        },
    )


@role_required(*ALL_ROLES)
def work_order_cancel(request, pk):
    work_order = get_object_or_404(_base_queryset(), pk=pk)
    if request.method == "POST":
        form = WorkOrderCancelForm(request.POST)
        if form.is_valid():
            if _run(request, work_order, services.CANCEL, reason=form.cleaned_data["reason"]):
                messages.success(request, "OT cancelada.")
                return redirect("workorder_detail", work_order.pk)
            return redirect("workorder_detail", work_order.pk)
    else:
        if services.CANCEL not in services.available_actions(work_order, request.user):
            return deny(request)
        form = WorkOrderCancelForm()
    return render(
        request, "workorders/work_order_cancel.html", {"wo": work_order, "form": form}
    )


# --- Manual corrective work order -------------------------------------------


@role_required(*services.REPORTER_ROLES)
def corrective_create(request, asset_pk):
    company = request.user.company
    if company is None:
        return deny(request)
    asset = get_object_or_404(Asset.objects.select_related("site", "category"), pk=asset_pk)
    can_assign = services.is_manager(request.user)

    if request.method == "POST":
        form = CorrectiveWorkOrderForm(
            request.POST, company=company, asset=asset, can_assign=can_assign
        )
        if form.is_valid():
            work_order = form.save(commit=False)
            work_order.company = company
            work_order.asset = asset
            work_order.type = WorkOrder.Type.CORRECTIVO
            work_order.origin = WorkOrder.Origin.MANUAL
            work_order.status = (
                WorkOrder.Status.ASIGNADA
                if work_order.assigned_to_id
                else WorkOrder.Status.ABIERTA
            )
            work_order.save()
            # Same snapshot the scheduler takes, from the template the
            # reporter chose. `resolve_checklist_template` is not used here:
            # that function answers "which version does this *plan* point at
            # now"; a manual work order has no plan, and the operator picked a
            # version explicitly from a list of active ones.
            services.snapshot_checklist(work_order, form.cleaned_data.get("checklist_template"))
            messages.success(request, f"OT correctiva #{work_order.pk} creada.")
            return redirect("workorder_detail", work_order.pk)
    else:
        form = CorrectiveWorkOrderForm(company=company, asset=asset, can_assign=can_assign)
    return render(
        request,
        "workorders/corrective_form.html",
        {"form": form, "asset": asset},
    )
