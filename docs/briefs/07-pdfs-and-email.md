# Brief 07 — PDFs (asset record, work-order report) and email

**Depends on:** 06.
**Goal:** the two audit documents customers pay for, downloadable and e-mailable.

## Build

1. **WeasyPrint** setup. Windows note for the owner's machine: if native install fails
   (GTK), run PDF generation inside the Docker `web` service — add that service to
   docker-compose in this brief. CI (Linux) installs system deps in the workflow.
2. **PDF 1 — Hoja de vida del equipo** (audit format, Spanish): company header (name,
   NIT, logo placeholder), ficha técnica completa + specs table, documents list,
   **full intervention history** (date, type, WO number, technician, verified by,
   downtime, cost), photos annex. Footer: generated-at timestamp + page numbers.
3. **PDF 2 — Informe de orden de trabajo** (matches the manual report the owner already
   issues): WO header (number, asset, type, priority, dates), checklist results table
   (item, result, value vs range, note), photo grid with captions, work done, downtime,
   costs, and the evidence block: **ejecutó** (name + timestamp) / **verificó** (name +
   timestamp) — pulled from the immutable WO record.
4. Download buttons on asset detail and WO detail (all roles can download within their
   company; PDFs stream via the gated-file pattern, never written to public media).
5. **Email**: SMTP config via env (`EMAIL_*` in `.env.example`); "Enviar por correo"
   action on both PDFs — modal asks recipient (default: current user's email), sends
   with PDF attached, Spanish subject/body templates.
6. **NotificationLog** model (company-scoped): channel (`email`), recipient, subject,
   related object (asset/WO), status (`enviado/fallido`), error detail, sent_by,
   sent_at. Every send attempt logs a row. This model is the future n8n/WhatsApp log too.
7. Failures (SMTP down) show a Spanish error and log `fallido` — never a 500.

## Out of scope

WhatsApp (Phase 2 via n8n), scheduled digests (brief 08 webhooks + Phase 2), annual
schedule PDF (Phase 2).

## Acceptance criteria

1. Hoja de vida PDF for a seeded asset returns valid PDF bytes containing asset code,
   company name and at least one history row (parse text in test).
2. WO report PDF contains executor and verifier names and every checklist item result.
3. A user from another company gets 404 on both PDF URLs (test).
4. Email send (locmem backend in tests) attaches a PDF, logs `enviado` with recipient;
   simulated SMTP failure logs `fallido` and shows a Spanish message, no 500 (test).
5. PDFs of a `verificada` WO are reproducible: two consecutive generations contain the
   same evidence fields (executor/verifier/timestamps).
6. Recipient field validates as email; body templates are Spanish.

## Definition of done

Per CLAUDE.md. Commit: `feat(reports): audit-grade asset and WO PDFs with email delivery`.
