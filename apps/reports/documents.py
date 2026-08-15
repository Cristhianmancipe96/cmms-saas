"""The two documents customers pay for, assembled from stored facts.

Split from `pdf.py` on purpose. Everything here is pure Python plus Django
templates: given an asset or a work order it produces the HTML, the file name
and the list of uploaded files the document is allowed to reach. Nothing in
this module needs WeasyPrint, which is what makes "does the report show the
verifier's name?" a question a test can ask directly instead of by decoding a
PDF.

Two rules the reads below encode rather than describe:

- **The work-order report is built from the snapshot, never from the template.**
  `WorkOrderChecklistItem` rows are the copy the technician actually signed
  off (CLAUDE.md rule 4). `ChecklistTemplate` is not imported here at all —
  the only thing the report says about it is its name, taken from the work
  order's own provenance FK.
- **Every read is filtered by `company_id` as well as by object id.** These
  reads are `.unscoped()` so a document can also be built from a management
  command or a future digest job, where no middleware has set the tenant
  contextvar. The isolation the scoped manager would have given is therefore
  written out, explicitly, on every query.
"""

import unicodedata
from dataclasses import dataclass, field

from django.template.loader import render_to_string
from django.utils import timezone

from apps.assets.models import Asset, AssetDocument
from apps.maintenance import services as maintenance_services
from apps.maintenance.models import MaintenancePlan
from apps.reports import pdf
from apps.workorders.models import WorkOrder, WorkOrderChecklistItem, WorkOrderPhoto

# The work-order report exists only once there is work to report on. Before
# that the document does not exist — which is why the view 404s rather than
# rendering an empty form.
REPORTABLE_STATUSES = WorkOrder.DONE_STATUSES

STYLESHEET = "css/vectron-pdf.css"
BRAND_MARK = "img/vectron-mark.svg"


@dataclass(frozen=True)
class Document:
    """A rendered document, ready for `pdf.render` or for an email attachment."""

    filename: str
    title: str
    html: str
    media_names: tuple[str, ...] = field(default_factory=tuple)

    def render_pdf(self) -> bytes:
        return pdf.render(self.html, allowed_media_names=self.media_names)


def _safe_slug(raw: str, fallback: str) -> str:
    """A file name an operator can recognise and a mail client will not mangle.

    ASCII-folded on purpose, not merely stripped of punctuation: the result
    goes into a `Content-Disposition` header, which Django encodes as latin-1,
    and an equipment code carrying a character outside it would turn a download
    into a 500. Accents fold to their base letter; anything else drops.
    """
    folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    kept = "".join(character if character.isalnum() else "-" for character in folded)
    trimmed = "-".join(part for part in kept.split("-") if part)
    return trimmed[:60] or fallback


def _base_context(company) -> dict:
    return {
        "company": company,
        "generated_at": timezone.localtime(),
        "stylesheet_url": pdf.static_url(STYLESHEET),
        "brand_mark_url": pdf.static_url(BRAND_MARK),
    }


# --- Hoja de vida -----------------------------------------------------------


def build_asset_record(asset: Asset) -> Document:
    """The equipment record an auditor asks for by name."""
    company = asset.company

    documents = (
        AssetDocument.objects.unscoped()
        .filter(company_id=company.pk, asset_id=asset.pk)
        .order_by("-uploaded_at")
    )
    plans = maintenance_services.annotate_due_state(
        MaintenancePlan.objects.unscoped()
        .filter(company_id=company.pk, asset_id=asset.pk, is_active=True)
        .order_by("name")
    )
    history = (
        WorkOrder.objects.unscoped()
        .filter(company_id=company.pk, asset_id=asset.pk, status__in=REPORTABLE_STATUSES)
        .select_related("completed_by", "verified_by")
        .order_by("-finished_at", "-id")
    )

    photo_name = asset.main_photo.name if asset.main_photo else ""
    media_names = (photo_name,) if photo_name else ()

    html = render_to_string(
        "reports/pdf/asset_record.html",
        {
            **_base_context(company),
            "doc_kind": "Hoja de vida del equipo",
            "asset": asset,
            "photo_url": pdf.media_url(media_names[0]) if media_names else "",
            "documents": documents,
            "plans": plans,
            "history": history,
            "downtime_total": sum(
                work_order.downtime_minutes or 0 for work_order in history
            ),
        },
    )
    return Document(
        filename=f"hoja-de-vida-{_safe_slug(asset.code, 'equipo')}.pdf",
        title=f"Hoja de vida · {asset.code}",
        html=html,
        media_names=media_names,
    )


# --- Informe de orden de trabajo --------------------------------------------


def build_work_order_report(work_order: WorkOrder) -> Document:
    """The intervention report, built from the frozen checklist."""
    company = work_order.company

    items = (
        WorkOrderChecklistItem.objects.unscoped()
        .filter(company_id=company.pk, work_order_id=work_order.pk)
        .order_by("order")
    )
    photos = (
        WorkOrderPhoto.objects.unscoped()
        .filter(company_id=company.pk, work_order_id=work_order.pk)
        .select_related("taken_by")
        .order_by("taken_at", "id")
    )

    photo_rows = [
        {"photo": photo, "url": pdf.media_url(photo.image.name)}
        for photo in photos
        if photo.image
    ]
    media_names = tuple(row["photo"].image.name for row in photo_rows)

    html = render_to_string(
        "reports/pdf/work_order_report.html",
        {
            **_base_context(company),
            "doc_kind": "Informe de orden de trabajo",
            "wo": work_order,
            "asset": work_order.asset,
            "items": items,
            "failures": [item for item in items if item.is_failure],
            "photo_rows": photo_rows,
        },
    )
    return Document(
        filename=f"informe-ot-{work_order.pk}-{_safe_slug(work_order.asset.code, 'equipo')}.pdf",
        title=f"Informe de OT #{work_order.pk}",
        html=html,
        media_names=media_names,
    )
