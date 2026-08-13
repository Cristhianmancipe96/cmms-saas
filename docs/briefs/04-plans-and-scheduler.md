# Brief 04 — Maintenance plans and idempotent scheduler

**Depends on:** 03.
**Goal:** preventive plans (weekly / monthly / quarterly / semiannual / annual, or by
usage hours) that auto-generate work orders exactly once.

## Build

1. `apps/maintenance`: **MaintenancePlan** (company-scoped): asset FK, name, kind
   (`preventivo/inspeccion/lubricacion/calibracion`), `frequency_type`
   (`calendar/meter`), `interval_days` (presets 7/15/30/90/180/365 + custom) or
   `meter_interval_hours`, checklist_template FK (latest active version resolved at
   WO-creation time), default_assignee (optional technician), `next_due_date`,
   estimated_minutes, is_active.
   **MeterReading** (company-scoped): asset FK, reading_hours (Decimal), read_at,
   source (`manual/work_order`), recorded_by. Readings must be monotonically
   non-decreasing per asset (validation with Spanish error).
2. **Scheduler** — management command `generate_work_orders` (designed to run daily via
   cron/Task Scheduler; document both):
   - Calendar plans: while `next_due_date <= today + horizon (default 0)`, create the WO
     for that due date and advance `next_due_date` by the interval (no drift: advance
     from the due date, not from today).
   - Meter plans: if `latest_reading - hours_at_last_generated_wo >= meter_interval_hours`,
     create a WO due today.
   - **Idempotency is structural**: `UNIQUE(plan_id, due_date)` on work orders +
     `get_or_create`. A crash halfway leaves a consistent, re-runnable state.
   - Summary output: created / skipped-existing / plans evaluated (this feeds n8n later).
3. Plan CRUD (Spanish, HTMX) from the asset detail page + a company-wide plan list with
   next-due and overdue highlighting. Meter reading quick-entry form on asset detail.
4. Work order creation here uses a `workorders` service stub — coordinate with brief 05's
   model (create the WO model in brief 05; in THIS brief, if 05 isn't merged yet, create
   the minimal WorkOrder model shell it specifies and leave execution UI to 05).

> Note: briefs 04 and 05 touch the same app surface. Execute them strictly in order.

## Out of scope

Work order execution/verification UI (05), notifications (08), KPI math (09).

## Acceptance criteria

1. Running `generate_work_orders` twice in a row creates zero new rows the second time
   (test literally runs it twice).
2. A weekly plan with `next_due_date` 3 weeks in the past generates the 3 missed WOs
   (catch-up) with correct historical due dates, and `next_due_date` lands in the future.
3. Monthly/annual advance correctly across month lengths (Jan 31 → Feb 28 handled).
4. Meter plan: readings 95h→210h with interval 100h generates exactly one WO; next one
   only after another 100h.
5. A meter reading lower than the previous is rejected (Spanish message).
6. Inactive plans and assets `dado_de_baja` generate nothing (test).
7. Cross-tenant isolation on plan URLs and on the command (company A's run context never
   touches B — command iterates per company).

## Definition of done

Per CLAUDE.md. Commit: `feat(maintenance): preventive plans and idempotent WO scheduler`.
