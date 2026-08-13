"""Per-request tenant context and subscription-suspension enforcement.

Both middlewares must sit after `AuthenticationMiddleware` in
`settings.MIDDLEWARE` (they read `request.user`) and before any view runs.
"""

from django.shortcuts import render
from django.urls import reverse

from apps.core.tenancy import current_company_id


class CurrentCompanyMiddleware:
    """Stores the current request's company id in a contextvar.

    Set unconditionally on every request (including anonymous ones, where it
    resolves to None) so no stale value from a previous request handled by
    the same worker thread can leak into this one.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        company_id = getattr(user, "company_id", None) if user else None
        token = current_company_id.set(company_id)
        try:
            return self.get_response(request)
        finally:
            current_company_id.reset(token)


class SuspensionMiddleware:
    """Blocks every page for a suspended/deactivated company's users, except
    logout. Two independent kill switches share this one gate:
    `Company.is_active` (a hard, platform-ops deactivation) and
    `Subscription.status == "suspended"` (billing-driven).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user
            and user.is_authenticated
            and not user.is_platform_admin
            and user.company_id is not None
            and request.path != reverse("logout")
        ):
            company = user.company
            subscription = getattr(company, "subscription", None)
            company_suspended = not company.is_active or (
                subscription is not None and subscription.status == "suspended"
            )
            if company_suspended:
                return render(request, "core/suspended.html", status=403)
        return self.get_response(request)
