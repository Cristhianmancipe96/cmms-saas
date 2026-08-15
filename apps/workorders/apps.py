from django.apps import AppConfig


class WorkOrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.workorders"
    label = "workorders"

    def ready(self):
        # Registers the post_save receiver that announces `ot_creada` to n8n
        # (apps/workorders/signals.py). Imported here, and nowhere else, so the
        # receiver is connected exactly once per process.
        from apps.workorders import signals  # noqa: F401
