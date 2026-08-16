"""The dashboard: the screen an administrator opens on Monday morning.

The view does no arithmetic. Every number on the page comes back from
`queries.py` already computed by Postgres — the only thing assembled here is
the per-asset table, which zips two result sets that were fetched by asset id.
Any formula that appeared in this file would be a second, untested copy of one
that already lives in SQL.

Who may look: admin and supervisor, because the numbers are how their work is
judged, and staff read-only, because the office asks «¿cuánto nos costó la
empacadora?» too. Technicians are not denied a screen they need — they have
«Mis OTs», which is their whole day; a plant-floor phone should not be showing
fleet MTBF.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.models import Site, User
from apps.core.rbac import deny, role_required
from apps.kpis import periods, queries

DASHBOARD_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.STAFF)


def _selected_site(request: HttpRequest) -> Site | None:
    """The site in `?sede=`, or None for "todas las sedes".

    Resolved through the scoped manager, so a site id belonging to another
    company reads as "no filter" instead of narrowing this company's numbers
    by a foreign row. The queries assert `company_id` themselves as well; this
    is the outer of the two locks.
    """
    raw = request.GET.get("sede")
    if not raw or not raw.isdigit():
        return None
    return Site.objects.filter(pk=int(raw)).first()


def _asset_table(mtbf: queries.Mtbf, availability: queries.Availability) -> list[dict]:
    """One row per asset that actually stopped or failed, worst first.

    Assets with a spotless period are left out on purpose: a table of twenty
    machines all reading 100 % is a table nobody scans. The empty state says so
    in words.
    """
    mtbf_by_asset = {row.asset_id: row for row in mtbf.by_asset}
    rows = []
    for asset in availability.by_asset:
        reliability = mtbf_by_asset.get(asset.asset_id)
        failures = reliability.failures if reliability else 0
        if not failures and not asset.downtime_minutes:
            continue
        rows.append(
            {
                "code": asset.code,
                "name": asset.name,
                "failures": failures,
                "downtime_minutes": asset.downtime_minutes,
                "availability": asset.percent,
                "mtbf_hours": reliability.hours if reliability else None,
            }
        )
    return rows[: queries.TOP_N]


@role_required(*DASHBOARD_ROLES)
def dashboard(request: HttpRequest) -> HttpResponse:
    # A platform admin has no company of their own, and cross-tenant analytics
    # is explicitly out of scope for this brief: there is no company_id to bind
    # into the queries, so there is nothing honest to show.
    if request.user.company_id is None:
        return deny(request)

    company_id = request.user.company_id
    period = periods.resolve(request.GET.get("periodo"))
    site = _selected_site(request)
    site_id = site.pk if site else None
    today = timezone.localdate()

    mtbf = queries.mtbf(company_id, period, site_id)
    mttr = queries.mttr(company_id, period, site_id)
    compliance = queries.pm_compliance(company_id, period, site_id)
    availability = queries.availability(company_id, period, site_id)
    backlog = queries.backlog(company_id, today, site_id)
    cost = queries.cost_by_asset_month(company_id, period, site_id)

    context = {
        "period": period,
        "period_choices": periods.PERIOD_CHOICES,
        "sites": Site.objects.all(),
        "selected_site": site,
        "selected_site_id": site_id,
        "today": today,
        "mtbf": mtbf,
        "mttr": mttr,
        "compliance": compliance,
        "availability": availability,
        "backlog": backlog,
        "cost": cost,
        "asset_rows": _asset_table(mtbf, availability),
    }
    # The switcher swaps only the numbers: the filter bar keeps the selection
    # the operator just made, and the page does not scroll back to the top.
    template = "kpis/_dashboard_body.html" if request.htmx else "kpis/dashboard.html"
    return render(request, template, context)
