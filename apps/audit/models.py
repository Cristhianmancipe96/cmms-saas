"""The black box: who did what, when — and nothing anyone can rewrite.

An audit log that some code path can edit is not an audit log; it is a table of
claims. So immutability here is built the same way the work-order seal is
(apps/workorders/models.py): not "no view offers a delete button", but every
door into the row refusing the write.

- `save()` accepts exactly one write per row — the insert. A second one raises,
  from a view, a shell, a management command or a signal handler alike.
- `delete()` always raises.
- `AuditLogQuerySet.update()` / `.delete()` raise too. Model overrides are
  invisible to `queryset.update()`, which goes straight to SQL, so a guard that
  a one-line `.update(object_repr="")` walks past would not be a guard.
- The Django admin registers it read-only *and* add-less (apps/audit/admin.py).

The second promise this table makes is that it never becomes a place to leak a
secret. Values are filtered on the way in by `services.SENSITIVE_FIELD_HINTS`:
a password hash, a token or a session key is stored as `[oculto]`, whatever the
caller passed. `changes` records field names and values of business data, never
credentials and never file contents.
"""

from django.conf import settings
from django.db import models

from apps.core.tenancy import CompanyScopedManager, CompanyScopedModel

IMMUTABLE_MESSAGE = (
    "El registro de auditoría es inmutable: sus filas no se editan ni se eliminan."
)


class AuditLogImmutable(Exception):
    """Raised on any attempt to modify or delete an audit row."""


class AuditLogQuerySet(models.QuerySet):
    """Extends the insert-only rule to bulk writes."""

    def update(self, **kwargs):
        raise AuditLogImmutable(IMMUTABLE_MESSAGE)

    def delete(self):
        raise AuditLogImmutable(IMMUTABLE_MESSAGE)


class AuditLog(CompanyScopedModel):
    class Action(models.TextChoices):
        CREATE = "create", "Creación"
        UPDATE = "update", "Edición"
        DELETE = "delete", "Eliminación"
        TRANSITION = "transition", "Cambio de estado"
        SEND = "send", "Envío"

    # PROTECT, like WorkOrder.completed_by: "who did this" is the whole point
    # of the row, and a NULL there would turn an answer into a shrug. Users are
    # deactivated in this product, never deleted, so nothing legitimate is
    # blocked by it.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="usuario",
        null=True,
        blank=True,
        help_text="Vacío solo cuando la acción la ejecuta el sistema (el programador).",
    )
    # Not derived from `user` at read time: the row must keep saying who acted
    # even after that person is renamed, exactly like NotificationLog.recipient
    # keeps the address the envelope actually carried.
    actor_label = models.CharField("usuario (nombre)", max_length=150, blank=True, default="")
    action = models.CharField("acción", max_length=20, choices=Action.choices)
    # "app_label.ModelName" rather than a ContentType FK: this table outlives
    # the models it describes, and a row about a model that was later renamed
    # or removed must still read correctly instead of pointing at a dangling
    # content-type id.
    model_label = models.CharField("modelo", max_length=60)
    object_id = models.BigIntegerField("id del objeto", null=True, blank=True)
    object_repr = models.CharField("objeto", max_length=255, blank=True, default="")
    changes = models.JSONField("cambios", default=dict, blank=True)
    # REMOTE_ADDR only. X-Forwarded-For is client-controlled unless a proxy is
    # known to overwrite it, and this deployment has no such proxy configured
    # yet (brief 11); recording a spoofable value as evidence is worse than
    # recording none.
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField("fecha", auto_now_add=True)

    objects = CompanyScopedManager.from_queryset(AuditLogQuerySet)()

    class Meta(CompanyScopedModel.Meta):
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"
        ordering = ["-created_at", "-id"]
        indexes = [
            *CompanyScopedModel.Meta.indexes,
            models.Index(fields=["-created_at"]),
            models.Index(fields=["model_label", "object_id"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} · {self.model_label} #{self.object_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditLogImmutable(IMMUTABLE_MESSAGE)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditLogImmutable(IMMUTABLE_MESSAGE)

    # --- Presentation -------------------------------------------------------

    @property
    def actor_name(self) -> str:
        return self.actor_label or (str(self.user) if self.user_id else "Sistema")

    @property
    def change_rows(self) -> list[dict]:
        """`changes` flattened for the template — one row per changed field.

        A dict is unordered to a template and `{{ value.de }}` on an arbitrary
        JSON blob is a shape the screen cannot rely on, so the shape is decided
        here: services.py always writes
        `{field: {"campo": label, "de": old, "a": new}}`.
        """
        rows = []
        for field, change in (self.changes or {}).items():
            if isinstance(change, dict) and ("de" in change or "a" in change):
                rows.append(
                    {
                        "field": change.get("campo") or field,
                        "old": change.get("de"),
                        "new": change.get("a"),
                    }
                )
            else:
                rows.append({"field": field, "old": None, "new": change})
        return rows
