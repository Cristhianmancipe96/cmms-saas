"""Downloading and emailing the two audit documents.

Every PDF here is generated on demand and handed straight to the response.
Nothing is written to `MEDIA_ROOT`, so there is no second, ungated copy of a
customer's audit evidence sitting behind a guessable URL — the same rule that
made photos flow through `assets.views.serve_file` (CLAUDE.md security rule 1),
applied to a file that would otherwise be *created* by the act of reading it.

Both objects are resolved through the tenant-scoped manager, so a primary key
from another company 404s before a single byte is rendered.
"""

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.models import User
from apps.assets.models import Asset
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core.rbac import deny, role_required
from apps.reports import documents, emails, pdf
from apps.reports.forms import RecipientsForm
from apps.reports.mailer import deliver_and_log
from apps.reports.models import NotificationLog
from apps.workorders.models import WorkOrder

ALL_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN, User.Role.STAFF)
# Generating a document is a read, so everyone in the company may do it.
# Putting it in someone's inbox is an act with a recipient and a record, so it
# sits with the roles that answer for the company's paperwork.
SENDER_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR)

PDF_CONTENT_TYPE = "application/pdf"


# --- Object lookups ---------------------------------------------------------


def _get_asset(pk) -> Asset:
    return get_object_or_404(
        Asset.objects.select_related("site", "category", "company"), pk=pk
    )


def _get_reportable_work_order(pk) -> WorkOrder:
    """A work order that has actually been executed.

    404 rather than a refusal page: before the work is finished the report does
    not exist. There is nothing to permit.
    """
    return get_object_or_404(
        WorkOrder.objects.select_related(
            "asset",
            "asset__site",
            "asset__category",
            "company",
            "assigned_to",
            "completed_by",
            "verified_by",
            "checklist_template",
            "plan",
        ),
        pk=pk,
        status__in=documents.REPORTABLE_STATUSES,
    )


# --- Rendering --------------------------------------------------------------


def _pdf_response(request, document: documents.Document, *, fallback_url: str):
    try:
        content = document.render_pdf()
    except pdf.PdfEngineUnavailable as error:
        # A missing print engine is a server problem, not the operator's. Say so
        # in Spanish and send them back to the screen they came from — never a
        # 500 page in front of a customer.
        messages.error(request, str(error))
        return redirect(fallback_url)
    response = HttpResponse(content, content_type=PDF_CONTENT_TYPE)
    # `inline`: on a phone this opens in the viewer instead of landing silently
    # in the downloads folder. The file name is still what gets saved.
    response["Content-Disposition"] = f'inline; filename="{document.filename}"'
    return response


@role_required(*ALL_ROLES)
def asset_record_pdf(request, pk):
    asset = _get_asset(pk)
    return _pdf_response(
        request,
        documents.build_asset_record(asset),
        fallback_url=reverse("asset_detail", args=[asset.pk]),
    )


@role_required(*ALL_ROLES)
def work_order_report_pdf(request, pk):
    work_order = _get_reportable_work_order(pk)
    return _pdf_response(
        request,
        documents.build_work_order_report(work_order),
        fallback_url=reverse("workorder_detail", args=[work_order.pk]),
    )


# --- Sending ----------------------------------------------------------------


def _send_screen(request, *, form, heading, summary, back_url):
    return render(
        request,
        "reports/send_form.html",
        {"form": form, "heading": heading, "summary": summary, "back_url": back_url},
    )


def _report_outcome(request, deliveries) -> None:
    sent = [delivery for delivery in deliveries if delivery.ok]
    failed = [delivery for delivery in deliveries if not delivery.ok]
    if sent:
        addresses = ", ".join(delivery.recipient for delivery in sent)
        messages.success(request, f"Documento enviado a {addresses}.")
    if failed:
        addresses = ", ".join(delivery.recipient for delivery in failed)
        messages.error(
            request,
            f"No se pudo enviar el correo a {addresses}. "
            "Quedó registrado como fallido; revisa la configuración de correo "
            "e inténtalo de nuevo.",
        )


def _handle_send(
    request,
    *,
    document: documents.Document,
    subject: str,
    body: str,
    kind: str,
    company,
    asset=None,
    work_order=None,
    recipients,
    fallback_url: str,
) -> bool:
    """Render, send, log. False means nothing was sent and the caller re-renders."""
    try:
        content = document.render_pdf()
    except pdf.PdfEngineUnavailable as error:
        messages.error(request, str(error))
        return False

    addresses = [user.email for user in recipients]
    deliveries = deliver_and_log(
        recipients=addresses,
        subject=subject,
        body=body,
        attachment=(document.filename, content, PDF_CONTENT_TYPE),
        company=company,
        kind=kind,
        sent_by=request.user,
        asset=asset,
        work_order=work_order,
    )
    # Brief 08: a document leaving the company is one of the things an auditor
    # asks about, so it leaves a row like every other consequential action. The
    # row is attached to the object the document is *about* — that is what
    # somebody reading the equipment's history is looking for.
    #
    # The addresses are recorded deliberately: "¿a quién se le mandó la hoja de
    # vida?" is the question, and the answer already lives one table over in
    # NotificationLog, under the same tenant scoping and the same admin-only
    # screens. What never enters an audit row is a credential — that rule is
    # enforced by apps/audit/services.py, not by this call site.
    audit.record(
        action=AuditLog.Action.SEND,
        instance=work_order or asset,
        user=request.user,
        company=company,
        changes=audit.note(
            documento=kind,
            destinatarios=addresses,
            enviados=sum(1 for delivery in deliveries if delivery.ok),
            fallidos=sum(1 for delivery in deliveries if not delivery.ok),
        ),
        request=request,
    )
    _report_outcome(request, deliveries)
    return True


@role_required(*SENDER_ROLES)
def asset_record_send(request, pk):
    company = request.user.company
    if company is None:
        # A platform admin passes the role gate but has no company, so there is
        # no list of colleagues to pick from and no tenant to bill the log to.
        return deny(request)
    asset = _get_asset(pk)
    back_url = reverse("asset_detail", args=[asset.pk])

    if request.method == "POST":
        form = RecipientsForm(request.POST, company=company)
        if form.is_valid():
            subject, body = emails.asset_record_message(asset=asset, sender=request.user)
            sent = _handle_send(
                request,
                document=documents.build_asset_record(asset),
                subject=subject,
                body=body,
                kind=NotificationLog.Kind.ASSET_RECORD,
                company=company,
                asset=asset,
                recipients=form.cleaned_data["recipients"],
                fallback_url=back_url,
            )
            if sent:
                return redirect(back_url)
    else:
        form = RecipientsForm(company=company, initial={"recipients": [request.user.pk]})

    return _send_screen(
        request,
        form=form,
        heading="Enviar hoja de vida por correo",
        summary=f"{asset.code} — {asset.name}",
        back_url=back_url,
    )


@role_required(*SENDER_ROLES)
def work_order_report_send(request, pk):
    company = request.user.company
    if company is None:
        return deny(request)
    work_order = _get_reportable_work_order(pk)
    back_url = reverse("workorder_detail", args=[work_order.pk])

    if request.method == "POST":
        form = RecipientsForm(request.POST, company=company)
        if form.is_valid():
            subject, body = emails.work_order_report_message(
                work_order=work_order, sender=request.user
            )
            sent = _handle_send(
                request,
                document=documents.build_work_order_report(work_order),
                subject=subject,
                body=body,
                kind=NotificationLog.Kind.WORK_ORDER_REPORT,
                company=company,
                asset=work_order.asset,
                work_order=work_order,
                recipients=form.cleaned_data["recipients"],
                fallback_url=back_url,
            )
            if sent:
                return redirect(back_url)
    else:
        form = RecipientsForm(company=company, initial={"recipients": [request.user.pk]})

    return _send_screen(
        request,
        form=form,
        heading="Enviar informe por correo",
        summary=f"OT #{work_order.pk} · {work_order.asset.code} — {work_order.asset.name}",
        back_url=back_url,
    )
