# Brief 09 — Dashboard and KPIs in raw SQL

**Depends on:** 08.
**Goal:** the numbers a maintenance manager (and an auditor) wants, computed with
hand-written, parameterized SQL.

## Build

1. `apps/kpis` with a query module (`kpis/sql.py`): each KPI is a named function running
   **raw SQL** via `connection.cursor()`, always `%s`-parameterized, always taking
   `company_id` and a date window (30/90/365 days). Document each query with its formula
   in `docs/kpis.md`.
   - **PM compliance**: preventive WOs verified on/before due date ÷ preventive WOs due
     in window.
   - **Backlog**: open+overdue WOs now, with aging buckets (≤7, 8–30, >30 days).
   - **MTTR**: avg (finished_at − started_at) over corrective WOs in window.
   - **MTBF**: per asset, avg time between consecutive corrective WOs in window (fleet
     average too).
   - **Availability**: 1 − (downtime_minutes ÷ window minutes), per asset and fleet.
   - **Cost per asset**: labor + parts in window, top 10, COP formatted.
   - **Requests funnel**: created/converted/rejected counts in window.
2. **Role-aware home page** (replaces the placeholder `/`):
   - Técnico: "mis OTs de hoy", overdue first, one-tap into execution.
   - Supervisor/Admin: KPI cards + overdue list + upcoming 7 days + latest requests.
   - Staff: read-only KPI cards.
3. Rendering: server-side only — stat cards, plain tables, CSS bar indicators. No JS
   chart library (keep the page fast on plant-floor phones). Window switcher 30/90/365
   via HTMX.
4. Seed-friendly: functions must return sane values on sparse data (no division by
   zero, Spanish empty states).

## Out of scope

Excel export and annual schedule matrix (Phase 2), cross-company/platform analytics.

## Acceptance criteria

1. Fixture scenario with hand-computed expected numbers (documented in the test):
   compliance %, MTTR, MTBF, availability, backlog buckets and top-cost all match
   exactly (single source-of-truth test class).
2. Every SQL function rejects/ignores rows from another company — seeding a second
   company with noisy data changes NOTHING in company A's numbers (test).
3. Zero-data company renders the dashboard with Spanish empty states, no errors, no
   division by zero (test).
4. No SQL string interpolation anywhere in `kpis/` (test greps the module for f-strings/
   `%` formatting on query text; params only).
5. Role rendering: technician home shows no KPI cards; staff shows no action buttons
   (tests).
6. Dashboard page renders in a single query batch per KPI (no N+1 on the lists —
   `assertNumQueries` upper bound).

## Definition of done

Per CLAUDE.md. Commit: `feat(kpis): raw-SQL maintenance KPIs and role-aware dashboard`.
