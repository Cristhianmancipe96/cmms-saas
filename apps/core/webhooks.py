"""Events for n8n — and the promise that n8n can be on fire without anyone
inside the plant noticing.

PLAN §7 states the rule this module implements: **if n8n falls, the CMMS keeps
working.** Everything here follows from taking that literally.

- **Nothing is emitted unless `N8N_WEBHOOK_URL` is configured.** Unset is the
  normal state (development, tests, a customer without automation) and it costs
  exactly one `if`.
- **The POST happens after the transaction commits, on a daemon thread.** After
  commit, because an event about a work order that a later rollback erased is a
  lie n8n cannot detect. On a thread, because the caller is a technician holding
  a phone: a dead endpoint that takes the full timeout to fail must not add
  those seconds to their screen.
- **Nothing here raises.** Every failure — bad URL, DNS, TLS, timeout, a 500
  from n8n — is logged and dropped. `emit` returning normally means "the event
  was handed off", never "it arrived".
- **The payload carries ids, not people.** `empresa_id`, the object's id and a
  handful of enum values. No names, no descriptions, no addresses, no photos:
  n8n queries back with its own token when it needs detail (next brief). Least
  privilege applies to messages in flight, not only to database rows.
- **The credential travels in a header, never in the body and never in a log.**
  Two headers, because they answer different questions: `X-Vectron-Token` says
  *who is calling* (n8n can reject an unknown caller before parsing anything),
  and `X-Vectron-Signature` — HMAC-SHA256 of the exact bytes sent, keyed with
  the same secret — says *this body was not altered on the way*, which is the
  rule CLAUDE.md states for webhooks. Redirects are refused outright, because
  urllib would carry the token to whatever host the redirect names
  (`_NoRedirects` below). The secret itself is read from the environment and
  appears in neither the payload nor any log line.

The transport is `urllib` from the standard library on purpose: this brief adds
an outbound HTTP call, not a dependency.
"""

import hashlib
import hmac
import json
import logging
import threading
import urllib.error
import urllib.request

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# The four events of this brief. `ot_vencida` is a per-run digest emitted by
# the scheduler (apps/maintenance/services.py) rather than one message per late
# work order: what n8n does with it is send one reminder to one supervisor, and
# forty separate events would be forty WhatsApp messages.
EVENT_WORK_ORDER_CREATED = "ot_creada"
EVENT_WORK_ORDER_OVERDUE = "ot_vencida"
EVENT_WORK_ORDER_VERIFIED = "ot_verificada"
EVENT_REQUEST_CREATED = "solicitud_creada"

TOKEN_HEADER = "X-Vectron-Token"
SIGNATURE_HEADER = "X-Vectron-Signature"
EVENT_HEADER = "X-Vectron-Event"

# Named so a test can find and join it (threading.enumerate). Production never
# joins: that is the whole point.
THREAD_NAME = "vectron-webhook"


def webhook_url() -> str:
    return getattr(settings, "N8N_WEBHOOK_URL", "") or ""


def webhook_token() -> str:
    return getattr(settings, "N8N_WEBHOOK_TOKEN", "") or ""


def timeout_seconds() -> float:
    return float(getattr(settings, "N8N_WEBHOOK_TIMEOUT", 3.0))


def is_configured() -> bool:
    return bool(webhook_url())


def signature(body: bytes, token: str) -> str:
    """HMAC-SHA256 of the exact bytes sent, hex, prefixed with its algorithm."""
    digest = hmac.new(token.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_envelope(event: str, *, company_id: int, object_type: str, object_id, data=None) -> dict:
    """The one payload shape. Ids and enums only — see the module docstring."""
    return {
        "evento": event,
        "ocurrido_en": timezone.now().isoformat(),
        "empresa_id": company_id,
        "objeto": {"tipo": object_type, "id": object_id},
        "datos": data or {},
    }


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects — because urllib would take the token along.

    `HTTPRedirectHandler` copies every custom header onto the follow-up
    request, including `X-Vectron-Token`, and it does so even when the new
    location is a different host. One misconfigured (or compromised) n8n
    instance answering `302 https://attacker.example/` would hand over the
    shared secret, and nothing in the CMMS would notice.

    Returning None turns the 3xx into an `HTTPError` here, which is logged and
    dropped like any other failure. A webhook receiver that wants to move house
    changes `N8N_WEBHOOK_URL`.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirects)


def _post(body: bytes, headers: dict) -> None:
    """The actual request. Runs on a daemon thread; swallows everything."""
    try:
        http_request = urllib.request.Request(
            webhook_url(), data=body, headers=headers, method="POST"
        )
        with _opener.open(http_request, timeout=timeout_seconds()) as response:
            status = getattr(response, "status", None)
            if status is not None and status >= 400:
                logger.warning("n8n rechazó el evento (HTTP %s)", status)
    except urllib.error.HTTPError as error:
        logger.warning("n8n rechazó el evento (HTTP %s)", error.code)
    except Exception as error:
        # Never the URL and never the headers: one carries a customer's
        # deployment, the other carries the token.
        logger.warning("No se pudo entregar el evento a n8n: %s", type(error).__name__)


def send(envelope: dict) -> threading.Thread | None:
    """Hand one envelope to a daemon thread. Returns it (tests join on it)."""
    if not is_configured():
        return None
    try:
        body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        token = webhook_token()
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            EVENT_HEADER: str(envelope.get("evento", "")),
        }
        if token:
            headers[TOKEN_HEADER] = token
            headers[SIGNATURE_HEADER] = signature(body, token)
        thread = threading.Thread(
            target=_post, args=(body, headers), name=THREAD_NAME, daemon=True
        )
        thread.start()
        return thread
    except Exception as error:  # pragma: no cover — thread creation, JSON encoding
        logger.warning("No se pudo preparar el evento para n8n: %s", type(error).__name__)
        return None


def emit(event: str, *, company_id: int, object_type: str, object_id, data=None) -> None:
    """Queue one event for after the current transaction commits.

    The business call sites call this and move on. It cannot raise: an
    automation is not allowed to break the operation that triggered it.
    """
    if not is_configured() or company_id is None:
        return
    try:
        envelope = build_envelope(
            event,
            company_id=company_id,
            object_type=object_type,
            object_id=object_id,
            data=data,
        )
        transaction.on_commit(lambda: send(envelope))
    except Exception as error:  # pragma: no cover — defensive: emit never raises
        logger.warning("No se pudo encolar el evento %s para n8n: %s", event, type(error).__name__)
