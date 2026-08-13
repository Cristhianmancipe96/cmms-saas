# Brief 08 — Failure requests, audit log, n8n webhook stub

**Depends on:** 07.
**Goal:** anyone can report a failure; everything relevant is traceable; the system can
already emit events for Phase-2 n8n automation.

## Build

1. `apps/requests_`: **MaintenanceRequest** (company-scoped): asset FK, reported_by
   (any role — staff included), description, optional photo (validated), status
   (`nueva/convertida/rechazada`), reviewed_by, review_note, linked work_order FK.
   - Big obvious "Reportar falla" button on asset detail and QR live view (all roles).
   - Supervisor/admin queue: convert → prefilled corrective WO (origin `solicitud`,
     links back) or reject with mandatory note. Reporter sees their requests' status.
2. **Audit log** (`apps/audit`): **AuditLog** (company-scoped): user, action
   (`create/update/delete/transition/login/send`), model label, object_id, object_repr,
   `changes` JSONB (old→new for changed fields, excluding file blobs), timestamp, IP.
   - Populate via the existing service layers (WO transitions, checklist versioning,
     asset baja, sends from brief 07, request convert/reject) + login/logout signals.
   - Admin/supervisor read-only screen with filters (user, model, date range).
     **Never log passwords, tokens or session data.**
3. **Webhook emitter** (`apps/core/webhooks.py`): if `N8N_WEBHOOK_URL` is set, POST JSON
   events `wo.created`, `wo.due_today`, `wo.overdue`, `wo.verified`,
   `request.created` with an **HMAC-SHA256 signature header** (`WEBHOOK_SECRET`).
   - Fire-and-forget with short timeout; failures log to NotificationLog (`webhook`
     channel, `fallido`) and never break the request cycle.
   - `wo.due_today` / `wo.overdue` are emitted by the brief-04 scheduler run summary.
   - Document payload schema in `docs/webhooks.md` (n8n consumes this in Phase 2).
4. Extend NotificationLog channel choices: `email/webhook` (whatsapp reserved).

## Out of scope

Actual n8n flows and WhatsApp (Phase 2), request SLA metrics (brief 09 counts them).

## Acceptance criteria

1. Staff user can create a request with photo; supervisor converts → corrective WO
   prefilled and linked; reporter sees status change (flow test).
2. Reject requires a note; the reporter sees the note (test).
3. WO transition, asset baja, checklist version-bump, email send and request decisions
   each produce an AuditLog row with correct old→new changes (tests).
4. AuditLog never contains password/token fields even when User rows change (test).
5. With `N8N_WEBHOOK_URL` set (mock server), `wo.verified` fires a signed payload —
   test recomputes and matches the HMAC; with the var unset, nothing fires.
6. A webhook endpoint that times out does not delay or fail the user's request (test
   with a slow mock).
7. Cross-tenant isolation on request and audit URLs (tests).

## Definition of done

Per CLAUDE.md. Commit: `feat(traceability): failure requests, audit log and signed webhooks`.
