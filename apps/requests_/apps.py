from django.apps import AppConfig


class MaintenanceRequestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    # The *module* keeps the trailing underscore, as the brief names it:
    # `apps/requests/` would sit one careless `import requests` away from
    # shadowing the HTTP library for anything running inside `apps/`.
    #
    # The *label* drops it, and not for taste: `CompanyScopedModel` builds its
    # reverse accessor as `%(app_label)s_%(class)s_set`, which with a trailing
    # underscore produces `requests__maintenancerequest_set` — a name Django
    # rejects outright (fields.E309, because `__` means "traverse a relation"
    # in a query). Renaming this one label is the fix that does not leave a
    # bespoke `related_name` on a base class every other model inherits.
    name = "apps.requests_"
    label = "requests"
    verbose_name = "solicitudes de mantenimiento"
