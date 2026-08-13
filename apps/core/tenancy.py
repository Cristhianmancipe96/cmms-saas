"""Row-level multi-tenancy machinery shared by every company-scoped model.

`current_company_id` is set once per request by `CurrentCompanyMiddleware`
(apps.core.middleware) and read by `CompanyScopedManager` so that the
*default* manager on any `CompanyScopedModel` subclass can never return
another company's rows — even from naive code such as `Model.objects.all()`
written inside a view. The only sanctioned bypass is the explicit
`Model.objects.unscoped()` call, reserved for platform-admin code paths.
"""

import contextvars

from django.db import models

current_company_id = contextvars.ContextVar("current_company_id", default=None)


class CompanyScopedManager(models.Manager):
    """Default manager for `CompanyScopedModel` subclasses.

    Every read (`.all()`, `.filter()`, `.get()`, ...) is transparently
    filtered to the current request's company. There is no implicit way to
    see other companies' rows — call `.unscoped()` explicitly instead.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        company_id = current_company_id.get()
        if company_id is None:
            return queryset.none()
        return queryset.filter(company_id=company_id)

    def unscoped(self):
        """Explicit, auditable bypass of tenant scoping. Platform-admin only."""
        return super().get_queryset()


class CompanyScopedModel(models.Model):
    """Abstract base for every tenant-owned business table."""

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
    )

    objects = CompanyScopedManager()

    class Meta:
        abstract = True
        indexes = [models.Index(fields=["company"])]
