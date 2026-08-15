import os

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET
from django.views.generic import DetailView, ListView

from apps.accounts.models import Site, User
from apps.assets import qr
from apps.assets import services as asset_services
from apps.assets.forms import (
    AssetBajaForm,
    AssetCategoryForm,
    AssetDocumentForm,
    AssetForm,
    parse_specs_from_post,
)
from apps.assets.models import Asset, AssetCategory, AssetDocument, AssetHasDocumentsError
from apps.core.rbac import RoleRequiredMixin, deny, role_required
from apps.maintenance import services as maintenance_services
from apps.maintenance import views as maintenance_views
from apps.workorders import services as workorder_services
from apps.workorders.models import WorkOrder

ALL_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN, User.Role.STAFF)
MANAGER_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR)

RECENT_WORK_ORDERS = 5


# --- Categories -------------------------------------------------------------


class AssetCategoryListView(RoleRequiredMixin, ListView):
    allowed_roles = ALL_ROLES
    model = AssetCategory
    template_name = "assets/category_list.html"
    context_object_name = "categories"


@role_required(*MANAGER_ROLES)
def category_create(request):
    if request.method == "POST":
        form = AssetCategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.company = request.user.company
            category.save()
            messages.success(request, f"Categoría {category.name} creada.")
            return redirect("assetcategory_list")
    else:
        form = AssetCategoryForm()
    return render(request, "assets/category_form.html", {"form": form})


# --- Assets -------------------------------------------------------------


class AssetListView(RoleRequiredMixin, ListView):
    allowed_roles = ALL_ROLES
    model = Asset
    template_name = "assets/asset_list.html"
    context_object_name = "assets"
    paginate_by = 25

    def get_queryset(self):
        queryset = Asset.objects.select_related("site", "category").all()
        params = self.request.GET
        if site_id := params.get("site"):
            queryset = queryset.filter(site_id=site_id)
        if category_id := params.get("category"):
            queryset = queryset.filter(category_id=category_id)
        if status := params.get("status"):
            queryset = queryset.filter(status=status)
        if criticality := params.get("criticality"):
            queryset = queryset.filter(criticality=criticality)
        if query := params.get("q", "").strip():
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(code__icontains=query)
                | Q(serial_number__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sites"] = Site.objects.all()
        context["categories"] = AssetCategory.objects.all()
        context["status_choices"] = Asset.Status.choices
        context["criticality_choices"] = Asset.Criticality.choices
        context["filters"] = self.request.GET
        return context


class AssetDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = ALL_ROLES
    model = Asset
    template_name = "assets/asset_detail.html"
    context_object_name = "asset"

    def get_queryset(self):
        return Asset.objects.select_related("site", "category").prefetch_related("documents")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["document_form"] = AssetDocumentForm()
        # Brief 04: the asset record is where preventive plans are created and
        # where the technician types the hour meter, so both panels live here.
        asset = self.object
        context["plans"] = maintenance_services.annotate_due_state(asset.maintenance_plans.all())
        context["can_manage_plans"] = (
            self.request.user.is_platform_admin or self.request.user.role in MANAGER_ROLES
        )
        context.update(maintenance_views.meter_panel_context(asset, user=self.request.user))
        # Brief 05: the equipment record is where a breakdown gets reported and
        # where its work-order history is read. Capped at the most recent few —
        # the full list, filtered by this asset, is one link away.
        context["work_orders"] = workorder_services.annotate_overdue(
            WorkOrder.objects.select_related("assigned_to").filter(asset=asset)[:RECENT_WORK_ORDERS]
        )
        context["can_report_failure"] = workorder_services.may_report_failure(self.request.user)
        return context


@role_required(*MANAGER_ROLES)
def asset_create(request):
    company = request.user.company
    if company is None:
        return deny(request)

    if request.method == "POST":
        form = AssetForm(request.POST, request.FILES, company=company)
        if form.is_valid():
            asset = form.save(commit=False)
            asset.company = company
            asset.created_by = request.user
            asset.specs = parse_specs_from_post(request.POST)
            asset.save()
            messages.success(request, f"Equipo {asset.name} creado.")
            return redirect("asset_detail", asset.pk)
    else:
        form = AssetForm(company=company)
    return render(
        request, "assets/asset_form.html", {"form": form, "specs": [], "is_create": True}
    )


@role_required(*MANAGER_ROLES)
def asset_update(request, pk):
    company = request.user.company
    asset = get_object_or_404(Asset, pk=pk)

    if request.method == "POST":
        form = AssetForm(request.POST, request.FILES, instance=asset, company=company)
        if form.is_valid():
            asset = form.save(commit=False)
            asset.specs = parse_specs_from_post(request.POST)
            asset.save()
            messages.success(request, f"Equipo {asset.name} actualizado.")
            return redirect("asset_detail", asset.pk)
    else:
        form = AssetForm(instance=asset, company=company)
    return render(
        request,
        "assets/asset_form.html",
        {"form": form, "specs": asset.specs, "is_create": False, "asset": asset},
    )


@role_required(*MANAGER_ROLES)
def asset_baja(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        form = AssetBajaForm(request.POST)
        if form.is_valid():
            asset.status = Asset.Status.DADO_DE_BAJA
            asset.baja_reason = form.cleaned_data["reason"]
            asset.save(update_fields=["status", "baja_reason", "updated_at"])
            messages.success(request, f"Equipo {asset.name} dado de baja.")
            return redirect("asset_detail", asset.pk)
    else:
        form = AssetBajaForm()
    return render(request, "assets/asset_baja_confirm.html", {"asset": asset, "form": form})


@role_required(*MANAGER_ROLES)
def asset_delete(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        try:
            asset.delete()
        except AssetHasDocumentsError as error:
            messages.error(request, str(error))
            return redirect("asset_detail", pk)
        except ProtectedError:
            # Brief 04 gave work orders a PROTECT FK to the asset they
            # document: they are audit evidence and outlive any wish to tidy
            # up the equipment list.
            messages.error(
                request,
                "No se puede eliminar un equipo con órdenes de trabajo. "
                "Usa 'Dar de baja' en su lugar.",
            )
            return redirect("asset_detail", pk)
        messages.success(request, f"Equipo {asset.name} eliminado.")
        return redirect("asset_list")
    return render(request, "assets/asset_delete_confirm.html", {"asset": asset})


@role_required(*MANAGER_ROLES)
def asset_document_upload(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        form = AssetDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)
            document.asset = asset
            document.company = asset.company
            document.uploaded_by = request.user
            document.save()
            messages.success(request, f"Documento {document.name} adjuntado.")
        else:
            for error_list in form.errors.values():
                for error in error_list:
                    messages.error(request, error)
    return redirect("asset_detail", asset.pk)


@role_required(*MANAGER_ROLES)
def asset_spec_row(request):
    """HTMX fragment: one empty specs key/value row, appended client-side."""
    return render(request, "assets/_specs_row.html", {"key": "", "value": ""})


# --- The QR flow (brief 06) -------------------------------------------------


@require_GET
def asset_scan(request, qr_uuid):
    """`/e/<qr_uuid>` — the sticker on the machine, resolved for whoever scanned it.

    The only view in this product without a `role_required` decorator, and
    the permission decision is more explicit for it, not less: it is
    `asset_services.scan_audience`, one function, called on the line below
    the lookup. Anonymous is a legitimate audience here — a QR glued to a
    machine is opened by people who are not logged in, and refusing them
    outright would make the label useless — but "legitimate" buys them the
    plate and nothing more.

    `require_GET` is the second half of the brief's rule that no write ever
    starts from a scan: not "there is no form on the page", but "this URL
    does not accept a POST at all".

    `.unscoped()` is required, not convenient: an anonymous request sets no
    tenant contextvar, so the scoped manager would match nothing and every
    scan would 404. The tenancy question the manager normally answers is
    asked one line later instead, explicitly, by `scan_audience`.
    """
    asset = get_object_or_404(
        Asset.objects.unscoped().select_related("site", "category"), qr_uuid=qr_uuid
    )
    audience = asset_services.scan_audience(request.user, asset)

    if audience == asset_services.PLATE:
        # Note what is NOT in this context: no asset object. A template can
        # only render what it was handed, so the plate cannot leak the
        # company, the status or a pk-bearing URL by way of some later edit
        # adding `{{ asset.something }}` — there is no `asset` to reach for.
        return render(
            request,
            "assets/scan_plate.html",
            {"code": asset.code, "name": asset.name},
        )

    return render(
        request,
        "assets/scan.html",
        {
            "asset": asset,
            "audience": audience,
            **asset_services.scan_context(asset, audience, request.user),
        },
    )


@role_required(*MANAGER_ROLES)
def asset_label(request, pk):
    """The printable sticker. Supervisors and admins only.

    Whoever prints a label decides what a machine answers to for the rest of
    its life, so this sits with the people who own the equipment list — not
    with everyone who can read it.
    """
    # `company` because the label prints the customer's own name on it.
    asset = get_object_or_404(Asset.objects.select_related("site", "company"), pk=pk)
    scan_url = qr.asset_scan_url(asset)
    return render(
        request,
        "assets/asset_label.html",
        {
            "asset": asset,
            "scan_url": scan_url,
            "qr_svg": qr.qr_svg(scan_url),
            "scan_url_is_local": qr.is_local_url(scan_url),
        },
    )


# --- Gated file downloads (CLAUDE.md security rule #1) ----------------------


@role_required(*ALL_ROLES)
def asset_photo_download(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if not asset.main_photo:
        raise Http404
    return serve_file(asset.main_photo)


@role_required(*ALL_ROLES)
def asset_document_download(request, pk):
    document = get_object_or_404(AssetDocument, pk=pk)
    if not document.file:
        raise Http404
    extension = os.path.splitext(document.file.name)[1]
    safe_base = "".join(c for c in document.name if c.isalnum() or c in " ._-").strip()
    download_name = f"{safe_base or 'documento'}{extension}"
    return serve_file(document.file, download_name=download_name)


def serve_file(field_file, download_name=None):
    """Stream a stored file to an already-authorized caller.

    Public on purpose, like `maintenance.views.meter_panel_context`: work-order
    photos (brief 05) are tenant data under exactly the same rule — never a
    guessable `/media/` URL — and a second copy of the "open it, guess the
    type, refuse if missing" logic is a second place for the two to drift.
    The *authorization* decision is not here; it stays in each calling view,
    next to the object it is about.
    """
    try:
        handle = field_file.open("rb")
    except (FileNotFoundError, ValidationError) as error:
        raise Http404 from error
    content_type = _guess_content_type(field_file.name)
    return FileResponse(
        handle,
        content_type=content_type,
        as_attachment=bool(download_name),
        filename=download_name,
    )


def _guess_content_type(filename: str) -> str:
    extension = os.path.splitext(filename)[1].lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(extension, "application/octet-stream")
