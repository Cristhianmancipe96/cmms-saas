"""The auditor's screen: one filterable, paginated list. Admin only.

Read-only by construction, not by omission — there is no edit URL to guard
because the model refuses the write anyway (apps/audit/models.py). What this
module has to get right is the other half: the rows a person may see. The
queryset goes through the scoped manager like every other list in the product,
so an admin of company A paging through this screen cannot reach a row of
company B even by guessing ids.
"""

from datetime import datetime

from django.views.generic import ListView

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.rbac import RoleRequiredMixin

# The models this product audits, with the name an operator would use. Also
# what fills the "modelo" filter: a `values_list("model_label").distinct()`
# would offer an empty dropdown on a fresh company and a raw
# "workorders.WorkOrder" on an old one.
AUDITED_MODELS = [
    ("workorders.WorkOrder", "Órdenes de trabajo"),
    ("requests.MaintenanceRequest", "Solicitudes de mantenimiento"),
    ("assets.Asset", "Equipos"),
    ("maintenance.MaintenancePlan", "Planes de mantenimiento"),
    ("accounts.User", "Usuarios"),
    ("reports.NotificationLog", "Envíos de documentos"),
]


def _parse_date(raw: str | None):
    """A date typed into the filter bar, or None. Never an exception."""
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


class AuditLogListView(RoleRequiredMixin, ListView):
    """Who did what, when — filtered by person, action, model and date range."""

    allowed_roles = (User.Role.ADMIN,)
    model = AuditLog
    template_name = "audit/audit_list.html"
    context_object_name = "entries"
    paginate_by = 50

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("user")
        params = self.request.GET
        if user_id := params.get("usuario"):
            queryset = queryset.filter(user_id=user_id)
        if action := params.get("accion"):
            queryset = queryset.filter(action=action)
        if model_label := params.get("modelo"):
            queryset = queryset.filter(model_label=model_label)
        if since := _parse_date(params.get("desde")):
            queryset = queryset.filter(created_at__date__gte=since)
        if until := _parse_date(params.get("hasta")):
            queryset = queryset.filter(created_at__date__lte=until)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        encoded = params.urlencode()
        context["querystring"] = f"{encoded}&" if encoded else ""
        context["filters"] = self.request.GET
        context["is_filtered"] = any(self.request.GET.values())
        context["action_choices"] = AuditLog.Action.choices
        context["model_choices"] = AUDITED_MODELS
        # Explicitly filtered by company: `User` is not a CompanyScopedModel,
        # so its default manager sees every tenant's rows. A filter dropdown is
        # a list of names, and a list of names is customer data.
        context["people"] = User.objects.filter(company=self.request.user.company).order_by(
            "username"
        )
        return context
