# Brief 05 — Work orders: state machine and mobile execution

**Depends on:** 04.
**Goal:** the heart of the product — corrective and preventive work orders executed from
a phone, verified by a different person, frozen as audit evidence.

## Build

1. `apps/workorders`: **WorkOrder** (company-scoped): asset FK, plan FK (null for
   corrective), type (`preventivo/correctivo/inspeccion`), origin (`plan/manual/solicitud`),
   status (`abierta → asignada → en_progreso → terminada → verificada`, plus `cancelada`),
   priority (`baja/media/alta/critica`), due_date, assigned_to, started_at, finished_at,
   failure_description, work_done, downtime_minutes, labor_cost_cop, parts_cost_cop,
   verified_by, verified_at, cancel_reason. `UNIQUE(plan, due_date)` (see brief 04).
   **WorkOrderChecklistItem**: WO FK + frozen snapshot fields (text, item_type, unit,
   min_value, max_value, required, order) + result (`ok/falla/na`), numeric_value, note.
   **WorkOrderPhoto**: WO FK, image, caption, taken_by, taken_at.
2. **Snapshot on creation**: when a WO is created from a plan, copy the template's
   items into WorkOrderChecklistItem rows. Template edits later never touch these.
3. **Transition service** (`workorders/services.py`) — single entry point
   `transition(wo, action, user)` with an explicit permission×state matrix:
   - assign → supervisor/admin; start, complete → the assigned technician (completing
     requires all `required` checklist items answered);
   - verify → supervisor/admin **and `user != executor`** (executor = who completed it);
   - cancel → supervisor/admin with mandatory reason; verified WOs cannot be cancelled.
   Invalid transitions raise; views translate to Spanish messages.
4. **Immutability**: once `verificada`, the WO and its checklist/photos reject any
   update or delete at the model layer (guard in `save()`/`delete()`), not just in views.
5. **Mobile execution screen** (the technician's home): checklist items saved per-item
   via HTMX as they're filled; numeric input validated against min/max — out-of-range
   marks the item `falla` visually; photo capture/upload (validated per CLAUDE.md);
   downtime and cost fields; big touch targets at 390px.
6. Views: "Mis OTs" for technicians (today / overdue / upcoming); supervisor list with
   filters (status, asset, technician, type, overdue); manual corrective WO form
   (prefill from asset); WO detail with timeline of transitions (who/when — feeds the
   audit log in brief 08).
7. Meter integration: completing a WO on a meter-tracked asset asks for the current
   reading (creates a MeterReading, source `work_order`).

## Out of scope

PDFs/email (07), failure requests (08), KPIs (09), QR entry point (06).

## Acceptance criteria

1. Full transition matrix test: every (state, action, role) combination — allowed ones
   succeed, all others raise (including verify on a non-`terminada` WO).
2. **The executor can never verify their own WO**, even if they are also a supervisor
   (test with a supervisor who self-executed).
3. A `verificada` WO rejects edits to itself, its checklist items and photos, and
   rejects deletion — at model level (tests bypass views on purpose).
4. Editing the checklist template after WO creation changes nothing in the WO's items
   (byte-identical snapshot test).
5. A WO cannot be completed while required items are unanswered (test); out-of-range
   numeric value stores `falla` (test).
6. Costs accept only non-negative integers (COP); downtime non-negative.
7. Cross-tenant 404s on every WO URL; technician A cannot open technician B's WO
   execution screen even in the same company (only assignee or supervisor/admin).

## Definition of done

Per CLAUDE.md. Commit: `feat(workorders): WO state machine, snapshots and mobile execution`.
