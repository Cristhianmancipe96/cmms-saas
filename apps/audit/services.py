"""Writing audit rows: the one way anything gets into the black box.

Call sites live in the service and view layers of the other apps — a work-order
transition, a request decision, an equipment edit, an invitation, a send. They
all come through `record`, so the questions "is this value safe to store?" and
"what shape does `changes` have?" are answered once.

Three rules this module keeps:

1. **Field names and values, never blobs and never secrets.** File fields are
   skipped entirely (`changes` describes what changed, it is not a second copy
   of the upload) and any field whose name looks like a credential is stored as
   `[oculto]` — see `SENSITIVE_FIELD_HINTS`. That check runs on the way in, on
   whatever the caller passed, so a future call site cannot leak a password by
   being careless with its `fields` list.
2. **A failed audit write fails the operation.** Deliberately unlike
   `apps/core/webhooks.py`, which is fire-and-forget: an automation that misses
   a message is an inconvenience, an action nobody can prove happened is the
   thing this product sells. `record` runs inside the caller's transaction and
   is allowed to raise.
3. **`changes` always has the same shape**: `{field: {"campo": label, "de":
   old, "a": new}}`. The screen renders it without knowing which model it is
   looking at.

A relation is stored as its id, not as the name of the thing it points at.
Resolving one would cost a query per foreign key per snapshot — two per field,
on every audited write, against a database that lives across the internet — and
the question people actually ask of this table ("who did this?") is already
answered in words by `actor_label` and `object_repr`.
"""

import datetime
from decimal import Decimal

from django.db import models

from apps.audit.models import AuditLog

REDACTED = "[oculto]"

# Substring hints, not an exact list: the check has to hold for fields that do
# not exist yet. `password` covers Django's own User.password (a hash — still
# not something an auditor's screen has any business displaying), `session`
# covers session keys, `key`/`token`/`secret` cover API credentials.
SENSITIVE_FIELD_HINTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "session",
    "api_key",
    "apikey",
    "private_key",
    "signature",
    "otp",
    "csrf",
)

MAX_REPR = 255
# A note or a description can be a page long. The audit row records *that it
# changed* and enough of it to recognise; the object itself keeps the full text.
MAX_VALUE_LENGTH = 500


def is_sensitive(field_name: str) -> bool:
    name = field_name.lower()
    return any(hint in name for hint in SENSITIVE_FIELD_HINTS)


def _json_value(value):
    """Anything the ORM hands us, as something JSONB can hold."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:MAX_VALUE_LENGTH]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, models.Model):
        return value.pk
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): (REDACTED if is_sensitive(str(key)) else _json_value(item))
            for key, item in value.items()
        }
    return str(value)[:MAX_VALUE_LENGTH]


def label_of(instance, field_name: str) -> str:
    """The Spanish name of a field, for the screen. Falls back to the field name."""
    try:
        return str(instance._meta.get_field(field_name).verbose_name)
    except Exception:
        return field_name


def snapshot(instance, fields) -> dict:
    """The stored value of each field, ready to be diffed.

    `value_from_object` rather than `getattr`: it returns the raw column value,
    so a ForeignKey yields its id without firing a query, and nothing in here
    can accidentally drag a related object (and its own fields) into the log.
    """
    data = {}
    for name in fields:
        if is_sensitive(name):
            data[name] = REDACTED
            continue
        try:
            field = instance._meta.get_field(name)
        except Exception:
            data[name] = _json_value(getattr(instance, name, None))
            continue
        if isinstance(field, models.FileField):
            # File blobs never enter the log (and neither do their storage
            # names: the log says a photo changed, the object holds the photo).
            continue
        data[name] = _json_value(field.value_from_object(instance))
    return data


def diff(before: dict, after: dict, *, instance=None) -> dict:
    """Only what actually changed, in the shape the audit screen expects."""
    changes = {}
    for name, new_value in after.items():
        old_value = before.get(name)
        if old_value == new_value:
            continue
        changes[name] = {
            "campo": label_of(instance, name) if instance is not None else name,
            "de": REDACTED if is_sensitive(name) else old_value,
            "a": REDACTED if is_sensitive(name) else new_value,
        }
    return changes


def created(instance, fields) -> dict:
    """`changes` for a brand-new row: every field, coming from nothing."""
    values = snapshot(instance, fields)
    return {
        name: {"campo": label_of(instance, name), "de": None, "a": value}
        for name, value in values.items()
    }


def note(**values) -> dict:
    """`changes` for an action that is not a field edit — a send, mostly.

    Same shape as everything else so the screen has one renderer, with `de`
    left empty: nothing was replaced, something happened.
    """
    return {
        name: {
            "campo": name.replace("_", " "),
            "de": None,
            "a": REDACTED if is_sensitive(name) else _json_value(value),
        }
        for name, value in values.items()
    }


def client_ip(request) -> str | None:
    if request is None:
        return None
    address = request.META.get("REMOTE_ADDR") or None
    return address


def record(
    *,
    action: str,
    instance,
    user=None,
    company=None,
    changes: dict | None = None,
    request=None,
    object_repr: str | None = None,
) -> AuditLog:
    """Write one audit row. Runs inside the caller's transaction.

    `company` defaults to the audited object's own company, which is what makes
    a row land in the right tenant even when the actor is a platform admin with
    no company of their own.
    """
    company_id = getattr(company, "pk", None) or getattr(instance, "company_id", None)
    if company_id is None:
        raise ValueError("Un registro de auditoría necesita una empresa.")

    safe_changes = {}
    for name, change in (changes or {}).items():
        if is_sensitive(name):
            safe_changes[name] = {"campo": name, "de": REDACTED, "a": REDACTED}
        else:
            safe_changes[name] = _json_value(change)

    return AuditLog.objects.create(
        company_id=company_id,
        user=user if getattr(user, "pk", None) else None,
        actor_label=str(user)[:150] if user is not None else "",
        action=action,
        model_label=f"{instance._meta.app_label}.{instance._meta.object_name}",
        object_id=instance.pk,
        object_repr=(object_repr if object_repr is not None else str(instance))[:MAX_REPR],
        changes=safe_changes,
        ip_address=client_ip(request),
    )
