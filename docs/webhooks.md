# Webhooks — what Vectron sends to n8n

Phase 2 automation (WhatsApp reminders, escalations) runs in n8n. Django decides
*that* something happened; n8n decides *who to tell and how*. This file is the
contract between the two.

Implementation: `apps/core/webhooks.py`. Nothing in here is required for the
CMMS to work — with `N8N_WEBHOOK_URL` unset, no event is built and no request is
made.

## Configuration

| Variable | Required | Meaning |
|---|---|---|
| `N8N_WEBHOOK_URL` | no | Where to POST. **Unset means the feature is off.** |
| `N8N_WEBHOOK_TOKEN` | no | Shared secret. Sent as a header; also the HMAC key. |
| `N8N_WEBHOOK_TIMEOUT` | no | Seconds, default `3.0`. |

The token is a secret: it lives in the environment, never in the repo, never in
a payload and never in a log line.

## Transport

`POST <N8N_WEBHOOK_URL>` with a JSON body and these headers:

| Header | Value |
|---|---|
| `Content-Type` | `application/json; charset=utf-8` |
| `X-Vectron-Event` | the event name, so n8n can route without parsing the body |
| `X-Vectron-Token` | the shared secret, verbatim |
| `X-Vectron-Signature` | `sha256=<hex>` — HMAC-SHA256 of the **exact bytes** of the body, keyed with the token |

Verify the signature, not just the token: a proxy that logs headers leaks a
token, while a signature only proves the body it was computed over.

```python
# n8n / any receiver
import hashlib, hmac
expected = "sha256=" + hmac.new(TOKEN.encode(), raw_body, hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, headers["X-Vectron-Signature"])
```

### Delivery semantics — read this before building a flow

- **At most once, and never guaranteed.** The POST happens on a background
  thread after the database transaction commits. If n8n is down, the event is
  logged as failed on our side and dropped. There is no retry queue: the CMMS
  must not be slowed down or held hostage by an automation tool (PLAN §7).
- **A missed event is not a lost fact.** Everything an event announces is a row
  in the database. A flow that must not miss anything should reconcile by
  querying, using the event as a nudge rather than as the source of truth.
- **Order is not guaranteed.** Two events emitted milliseconds apart travel on
  different threads.
- **Answer fast.** Our client gives up after `N8N_WEBHOOK_TIMEOUT` seconds. Do
  the work in a queue on your side, not in the webhook response.

## Payload

One shape for every event:

```json
{
  "evento": "ot_verificada",
  "ocurrido_en": "2026-08-15T14:31:02.104512-05:00",
  "empresa_id": 12,
  "objeto": { "tipo": "orden_de_trabajo", "id": 3481 },
  "datos": { "estado": "verificada", "equipo_id": 77, "tipo": "correctivo", "origen": "solicitud" }
}
```

`ocurrido_en` is ISO-8601 in `America/Bogota`.

**The payload carries ids and enum values — never people, never free text.** No
names, no e-mail addresses, no descriptions, no equipment specifications. n8n
asks the API for whatever detail it needs, with its own credentials, at the
moment it needs it. A webhook body that ends up in a log, a proxy or the wrong
inbox must not be enough to learn who works here or what broke.

## Events

### `ot_creada`
Emitted whenever a work order is created — by the scheduler, by the manual
corrective form, or by converting a failure report.

`objeto`: `{"tipo": "orden_de_trabajo", "id": <id>}`

| `datos` | Meaning |
|---|---|
| `equipo_id` | Asset id |
| `tipo` | `preventivo` · `correctivo` · `inspeccion` |
| `origen` | `plan` · `manual` · `solicitud` |
| `prioridad` | `baja` · `media` · `alta` · `critica` |
| `estado` | Always `abierta` or `asignada` at birth |
| `fecha_programada` | `YYYY-MM-DD` or `null` |
| `solicitud_id` | The failure report it came from, or `null` |

### `ot_vencida`
Emitted **once per company per scheduler run**, and only when there is
something to report. A digest, not one message per late work order: forty
overdue work orders are one problem for a supervisor, not forty notifications.

`objeto`: `{"tipo": "empresa", "id": <company id>}`

| `datos` | Meaning |
|---|---|
| `total` | How many open work orders are past their date |
| `ordenes` | Their ids, oldest first |

### `ot_verificada`
A supervisor verified a work order. The row is now sealed evidence and will
never change again.

`objeto`: `{"tipo": "orden_de_trabajo", "id": <id>}`

| `datos` | Meaning |
|---|---|
| `estado` | Always `verificada` |
| `equipo_id`, `tipo`, `origen` | As in `ot_creada` |

### `solicitud_creada`
Somebody reported a failure. Nobody has decided anything yet — this is the event
that should make a supervisor's phone buzz.

`objeto`: `{"tipo": "solicitud", "id": <id>}`

| `datos` | Meaning |
|---|---|
| `equipo_id` | Asset id |
| `estado` | Always `nueva` |

## Testing a receiver

Point `N8N_WEBHOOK_URL` at any endpoint that accepts a POST (a webhook.site URL,
a local `nc -l`), set a token, and verify a work order. `apps/core/tests/
test_webhooks.py` does exactly this against a throwaway HTTP server, including
the "n8n is hanging" and "n8n is dead" cases.

## Not in this brief

Incoming calls from n8n to Django (a read API with its own token, and callbacks
that verify the signature) are the next Phase-2 step. Nothing in this document
authorises n8n to write anything.
