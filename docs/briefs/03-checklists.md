# Brief 03 — Checklist templates with versioning

**Depends on:** 02.
**Goal:** reusable maintenance checklists per machine type, versioned so past evidence
never mutates.

## Build

1. `apps/checklists`: **ChecklistTemplate** (company-scoped: name, optional
   AssetCategory FK, `version` int, `is_active`, `parent` FK to previous version or
   null), **ChecklistTemplateItem** (template FK, order, text, item_type
   `check/numeric/text`, unit, min_value, max_value, required).
2. **Versioning rule in a service layer** (`checklists/services.py`): once a template
   version has been referenced by any work order (brief 05 will create the FK; design
   for it now via a `is_locked` computed check), editing items **creates version n+1**
   (copy items, apply edits, deactivate parent). Unused templates edit in place.
3. Builder UI (Spanish, HTMX): create template, add/edit/reorder items (up/down
   buttons, no JS libs), numeric items ask unit/min/max, duplicate-template action,
   deactivate.
4. Template list with filter by category and active state; show version chain.
5. Factories for both models (including a realistic "Flowpac inspección semanal"
   template in factory helpers for reuse in tests/seeds).

## Out of scope

Filling checklists (that's a work-order concern, brief 05), PDF rendering (brief 07).

## Acceptance criteria

1. Editing a locked (used) template produces version n+1 with edits applied, parent
   deactivated and untouched in DB (test asserts old items byte-identical).
2. Editing an unused template mutates in place, version unchanged.
3. Items keep explicit order; reorder persists (test).
4. `numeric` items require min ≤ max and a unit; invalid ranges rejected with Spanish
   message.
5. Cross-tenant: company B gets 404 on A's template URLs (test).
6. Permissions: admin/supervisor manage; technician/staff read-only (matrix test).

## Definition of done

Per CLAUDE.md. Commit: `feat(checklists): versioned checklist templates and builder`.
