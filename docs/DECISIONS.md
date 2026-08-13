# Decision log (ADRs)

Newest first. Format: what / why / what was rejected.

---

## 2026-08-13 · Stack: Django 5 + HTMX + PostgreSQL

**What:** Django monolith with HTMX-driven templates; PostgreSQL with JSONB for flexible
asset specs; WeasyPrint for PDF generation; pytest + GitHub Actions + pre-commit (gitleaks).
**Why:** a CMMS is a CRUD-heavy, forms-and-permissions domain. Django ships ORM,
migrations, auth, permissions and an admin back office out of the box — fastest path to a
billable product, all in Python. SQL is still learned deliberately: every dashboard KPI is
written in raw SQL.
**Rejected:** FastAPI + React (two stacks to learn, slower to ship; FastAPI credibility
comes later via the public API / MCP server), Flask (everything hand-rolled), Firebase
(the whole point is SQL).

## 2026-08-13 · Row-level multi-tenancy from day one

**What:** every business table carries `company_id`; queries are globally scoped; a
`subscriptions` table exists from the first migration. Self-service signup and billing
arrive in Phase 3.
**Why:** turning a validated pilot into a SaaS must not require a painful migration.
**Rejected:** schema-per-tenant (operational complexity an SMB SaaS doesn't need yet;
Postgres RLS kept as future hardening), single-tenant (guaranteed rework).

## 2026-08-13 · Public repo, no OSS license

**What:** public GitHub repo, README/commits/ADRs in English, no LICENSE file (all rights
reserved).
**Why:** public evidence of engineering process; without a license the code cannot be
legally redistributed or resold, so the portfolio goal is met without giving the product
away.
**Conditions:** gitleaks on pre-commit, fictional seed data only, pilot-customer data never
enters the repo.
**Rejected:** MIT (gives the SaaS away), private repo (defeats the evidence goal).

## 2026-08-13 · Pilot: companies running Flowpac packaging machines; generic data model

**What:** validate with companies operating Flowpac (flow-pack) machines, while keeping
the model machine-agnostic: user-defined asset categories and JSONB technical sheets.
**Why:** founder has direct access to that niche; food-packaging plants face INVIMA/GMP
audits, so the pain is acute and concrete. Generic because the end product targets any
machinery.
**Rejected:** building generic with no pilot (unvalidated features).

## 2026-08-13 · Business model: monthly subscription per company

**What:** per-company monthly subscription with plan limits (assets, users); trial;
suspension on non-payment. Manual invoicing first; recurring card payments (Wompi) once
past ~3 paying companies.
**Why:** recurring revenue; per-company (not per-user) pricing as an SMB differentiator.
**Rejected:** one-time license; per-user pricing.

## 2026-08-13 · Notifications: email first, WhatsApp via n8n in Phase 2

**What:** MVP sends PDFs over SMTP straight from Django. n8n arrives in Phase 2 for
reminders, weekly digests and escalations; WhatsApp through Meta Cloud API (already
operated in another production project) or Evolution API — decided in Phase 2 with
measured cost per message.
**Why:** the core must work with zero integration dependencies; n8n only delivers
messages — business rules live in Django, under pytest.
**Rejected:** WhatsApp inside the MVP (cost/risk before the core is validated); business
logic inside n8n flows (invisible to tests, fragile).
