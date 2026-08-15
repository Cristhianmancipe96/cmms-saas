"""Failure-report screens.

Two audiences with opposite needs, which is why the list is one view with two
querysets rather than two views:

- **whoever found the machine stopped** wants to type one sentence, attach one
  photo and leave — and later, to know what happened to it;
- **the supervisor** wants a queue, filtered, with a decision at the end of
  each row.

Every object is resolved through `services.visible_to` / `services.may_see`, so
a report belonging to another company 404s (an existence oracle is a leak too)
and a report belonging to a colleague is invisible to a technician who did not
file it.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.accounts.models import User
from apps.assets.models import Asset
from apps.assets.views import serve_file
from apps.core.rbac import RoleRequiredMixin, deny, role_required
from apps.requests_ import services
from apps.requests_.forms import (
    MaintenanceRequestForm,
    RequestConvertForm,
    RequestRejectForm,
)
from apps.requests_.models import MaintenanceRequest

ALL_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN, User.Role.STAFF)


def _querystring_without_page(params) -> str:
    kept = params.copy()
    kept.pop("page", None)
    encoded = kept.urlencode()
    return f"{encoded}&" if encoded else ""


# --- Reporting --------------------------------------------------------------


@role_required(*ALL_ROLES)
def request_create(request, asset_pk):
    """«Reportar falla» — the one screen every role in the company can write to."""
    if request.user.company_id is None:
        # A platform admin passes the role gate but has no company to file
        # against, and this form has no "on behalf of which company" selector.
        return deny(request)
    asset = get_object_or_404(Asset.objects.select_related("site", "category"), pk=asset_pk)

    if request.method == "POST":
        form = MaintenanceRequestForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                created = services.create_request(
                    asset=asset,
                    user=request.user,
                    description=form.cleaned_data["description"],
                    photo=form.cleaned_data.get("photo"),
                    http_request=request,
                )
            except services.RequestError as error:
                messages.error(request, str(error))
                return redirect("asset_detail", asset.pk)
            messages.success(
                request,
                f"Falla reportada (solicitud #{created.pk}). "
                "Un supervisor la revisa y te avisa aquí mismo.",
            )
            return redirect("maintenancerequest_detail", created.pk)
    else:
        form = MaintenanceRequestForm()
    return render(request, "requests_/request_form.html", {"form": form, "asset": asset})


# --- Lists ------------------------------------------------------------------


class MaintenanceRequestListView(RoleRequiredMixin, ListView):
    allowed_roles = ALL_ROLES
    template_name = "requests_/request_list.html"
    context_object_name = "requests"
    paginate_by = 25

    def get_queryset(self):
        queryset = services.visible_to(self.request.user)
        params = self.request.GET
        if status := params.get("estado"):
            queryset = queryset.filter(status=status)
        if asset_id := params.get("equipo"):
            queryset = queryset.filter(asset_id=asset_id)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        can_review = services.may_review(self.request.user)
        context["can_review"] = can_review
        context["status_choices"] = MaintenanceRequest.Status.choices
        context["assets"] = Asset.objects.order_by("name")
        context["filters"] = self.request.GET
        context["querystring"] = _querystring_without_page(self.request.GET)
        context["is_filtered"] = any(self.request.GET.values())
        context["open_count"] = self.object_list.filter(
            status=MaintenanceRequest.Status.NUEVA
        ).count()
        return context


# --- Detail and decisions ---------------------------------------------------


def _get_visible_request(request, pk) -> MaintenanceRequest:
    request_obj = get_object_or_404(services.base_queryset(), pk=pk)
    if not services.may_see(request_obj, request.user):
        # 404, not 403: to a technician who did not file it, a colleague's
        # report does not exist.
        raise Http404
    return request_obj


@role_required(*ALL_ROLES)
def request_detail(request, pk):
    request_obj = _get_visible_request(request, pk)
    can_review = services.may_review(request.user)
    return render(
        request,
        "requests_/request_detail.html",
        {
            "solicitud": request_obj,
            # From the join `base_queryset` already paid for, not a second
            # query. `RelatedObjectDoesNotExist` subclasses AttributeError, so
            # `getattr` with a default is the sanctioned way to ask a reverse
            # one-to-one "is there one?" without a try/except.
            "work_order": getattr(request_obj, "work_order", None),
            "can_review": can_review,
            "can_decide": can_review and request_obj.is_open,
            "convert_form": RequestConvertForm() if can_review else None,
        },
    )


@role_required(User.Role.ADMIN, User.Role.SUPERVISOR)
@require_POST
def request_convert(request, pk):
    """One click: report → corrective work order. Two clicks: the same one."""
    request_obj = get_object_or_404(services.base_queryset(), pk=pk)
    form = RequestConvertForm(request.POST)
    priority = form.cleaned_data["priority"] if form.is_valid() else None
    try:
        work_order = services.convert(
            request_obj, user=request.user, priority=priority, http_request=request
        )
    except services.RequestError as error:
        messages.error(request, str(error))
        return redirect("maintenancerequest_detail", request_obj.pk)
    messages.success(request, f"Solicitud convertida en la OT correctiva #{work_order.pk}.")
    return redirect("workorder_detail", work_order.pk)


@role_required(User.Role.ADMIN, User.Role.SUPERVISOR)
def request_reject(request, pk):
    """Rejecting gets its own screen, because it costs a written reason."""
    request_obj = get_object_or_404(services.base_queryset(), pk=pk)
    if request.method == "POST":
        form = RequestRejectForm(request.POST)
        if form.is_valid():
            try:
                services.reject(
                    request_obj,
                    user=request.user,
                    note=form.cleaned_data["note"],
                    http_request=request,
                )
            except services.RequestError as error:
                messages.error(request, str(error))
                return redirect("maintenancerequest_detail", request_obj.pk)
            messages.success(request, "Solicitud rechazada. Quien la reportó ve el motivo.")
            return redirect("maintenancerequest_detail", request_obj.pk)
    else:
        if not request_obj.is_open:
            messages.error(request, "Esta solicitud ya fue decidida.")
            return redirect("maintenancerequest_detail", request_obj.pk)
        form = RequestRejectForm()
    return render(
        request, "requests_/request_reject.html", {"solicitud": request_obj, "form": form}
    )


@role_required(*ALL_ROLES)
def request_photo_download(request, pk):
    """The attached photo is tenant data: served through here, never as a
    guessable public /media/ URL (CLAUDE.md security rules)."""
    request_obj = _get_visible_request(request, pk)
    if not request_obj.photo:
        raise Http404
    return serve_file(request_obj.photo)
