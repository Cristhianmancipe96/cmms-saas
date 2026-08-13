# CLAUDE.md — house rules for every agent session

This is a multi-tenant CMMS SaaS (equipment records, preventive maintenance, work
orders, audit evidence) for Spanish-speaking SMBs. The owner/PM is Cristhian; an
independent reviewer (another Claude session) audits every brief after it lands.

## How work happens here

- Work is delivered in **briefs**: `docs/briefs/NN-*.md`. Execute exactly ONE brief per
  session, exactly as scoped. Check `docs/briefs/STATUS.md` first: never start a brief
  whose dependencies aren't ticked, never re-do a ticked brief.
- **Stay inside the brief.** No opportunistic refactors, no features from later briefs,
  no edits to `docs/briefs/*` content (only tick STATUS.md when done).
- If the brief is ambiguous or conflicts with this file, STOP and ask the owner instead
  of guessing.

## Stack (decided — do not relitigate)

Python 3.12 · Django 5 · PostgreSQL 16 (never SQLite, not even for tests) · HTMX +
Django templates (no React/Vue/build step; htmx and Pico CSS are vendored in `static/`)
· `uv` for dependencies · pytest + pytest-django + factory-boy · ruff · WeasyPrint for
PDFs · Docker Compose for the dev database. See `docs/DECISIONS.md` for why.

Commands: `docker compose up -d db` · `uv run pytest -q` · `uv run ruff check .` ·
`uv run python manage.py <cmd>`

## Architecture rules (violating any of these = the brief is NOT done)

1. **Tenant isolation is sacred.** Every business table carries `company_id`. All ORM
   access goes through the scoped manager (`objects` filtered by current company);
   cross-company access by URL manipulation must 404. Every view brief ships at least
   one test proving company A cannot reach company B's data.
2. **RBAC:** roles are `admin`, `supervisor`, `technician`, `staff` (+ `is_platform_admin`
   cross-tenant). Enforce with the shared `role_required` mixin/decorator — never ad-hoc
   `if` checks scattered in views.
3. **The executor never verifies their own work.** A work order is `verified` only by a
   supervisor/admin who is not the user who executed it.
4. **Verified work orders are immutable** — they are audit evidence. Checklist results
   are snapshots: later edits to templates must never alter past work orders.
5. **The scheduler is idempotent.** Auto-generation of work orders relies on
   `UNIQUE(plan_id, due_date)` + `get_or_create`. Running it twice creates nothing new.
6. **Business logic lives in Django** (services + models, covered by pytest), never in
   n8n. n8n only delivers messages (Phase 2, webhook stub only for now).
7. **Raw SQL only for the KPI dashboard**, always parameterized (`%s`), always filtered
   by `company_id`. Everything else uses the ORM.
8. **UI text in Spanish (es-CO); code, comments, commits and docs in English.**
   `TIME_ZONE = "America/Bogota"`. Money in COP (integer pesos).
9. **Mobile-first**: technicians operate from a phone on a plant floor. Every technician
   screen must be usable at 390px width.
10. **No secrets in the repo. Ever.** Config via environment (`.env` git-ignored,
    `.env.example` maintained). gitleaks runs on pre-commit; never bypass it.

## Security — the owner's #1 priority (stated 2026-08-13)

Customer data protection outranks features and speed. Concretely:

- **Deny by default.** Every view requires authentication + role check + tenant scoping;
  a view without an explicit permission decision is a bug.
- **Uploaded files (photos, manuals, documents) are tenant data.** They are served only
  through an auth- and company-checked view — never as directly guessable public
  `/media/` URLs in production.
- CSRF stays on everywhere; forms only via POST; no `csrf_exempt` without written
  justification in the brief summary.
- Raw SQL only in the KPI module, always `%s`-parameterized — string-built SQL is an
  automatic fail. ORM everywhere else.
- Validate every upload: extension + content-type whitelist, max size; images
  re-encoded via Pillow (strips active payloads and EXIF).
- Login hardening: throttle/lockout on repeated failures; session cookies `HttpOnly`,
  `Secure` in production, `SameSite=Lax`; sensible session expiry.
- No PII or credentials in logs. Audit log records who/what/when — not passwords, not
  tokens.
- Webhooks (n8n) are HMAC-signed; incoming callbacks verify the signature.
- Production settings must pass `manage.py check --deploy` (see brief 11).
- Personal data of Colombian customers falls under **Ley 1581 (habeas data)** — collect
  the minimum, never copy real customer data into seeds, fixtures or the public repo.

## Definition of done (every brief)

1. All acceptance criteria in the brief have a passing test.
2. `uv run pytest -q` green · `uv run ruff check .` clean · pre-commit hooks pass.
3. Migrations committed; `.env.example` updated if new config appeared.
4. Conventional commit in **English**: `feat(assets): asset record CRUD with JSONB specs`
   — one commit per brief is fine; push to `main`.
5. Tick the brief in `docs/briefs/STATUS.md` (same commit).
6. Print a short summary for the owner: what landed, how to try it in the browser in
   2 minutes, anything deferred.

## Quality bar

Production discipline, junior-proof: no commented-out code, no `print()` debugging left
behind, no TODOs without an issue, explicit `on_delete`, `select_related` where lists
render FKs, factories for every model. If a test is hard to write, the design is wrong —
fix the design, not the test.
