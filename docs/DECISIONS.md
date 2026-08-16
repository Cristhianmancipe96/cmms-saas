# Decision log (ADRs)

Newest first. Format: what / why / what was rejected.

---

## 2026-08-16 · Production settings as a thin overlay module, not a settings package

**What:** `config/settings.py` stays as it is and remains the development and test
profile. Production runs `config/settings_prod.py`, which imports it and overrides what
changes once the site is on the internet. `DEBUG = False` is a literal there — no
environment variable can flip it — and `DEBUG=True` in the environment raises
`ImproperlyConfigured` at import instead of being ignored.
**Why:** the brief's requirement was that `DEBUG=True` in production be *impossible*, not
unlikely. A literal in a module that production always loads is impossible; a variable
with a safe default is merely unlikely. Keeping the base module in place also meant the
678-test suite, `conftest.py` and CI kept working untouched — the split introduced no risk
to anything already green.
**Rejected:** a `config/settings/{base,dev,prod}.py` package (the textbook layout, but it
renames the module every existing entry point names, for no behavioural gain); one file
with `if not DEBUG:` branches (the production configuration would then be reachable only
by reading the whole file, and nothing prevents `DEBUG=True`); `django-configurations`
(a dependency to express a fifteen-line difference).

## 2026-08-16 · The deploy unit is a Dockerfile, not a platform-specific file

**What:** one `Dockerfile` at the repository root, plus `docker-entrypoint.sh` which
applies migrations and then execs gunicorn. No `Procfile`, no `railway.toml`, no
`app.json`. CI builds the image and boots it against a real database on every push.
**Why:** the platform is not decided and should not have to be. Railway, Render and Fly
all build a plain Dockerfile from the repository, and a VPS runs the same image with
`docker run` — so the choice of platform stays reversible and the thing that was tested
in CI is byte-for-byte the thing that runs. It also solves the WeasyPrint problem: the
image installs Pango and HarfBuzz, so PDFs render in production even though they cannot
render on the owner's Windows machine.
**Why migrations in the entrypoint:** with `set -e`, a failed migration exits the
container instead of starting a web server on a half-migrated database. The cost is that
two replicas starting at once would race, which is why `docs/deploy.md` says one instance
and says why.
**Rejected:** buildpacks (implicit, platform-specific, and cannot install Pango without
escape hatches); `railway.toml` (locks the deploy to one vendor); running migrations as a
manual step (it is the step people forget, and forgetting it produces 500s rather than a
clear failure).

## 2026-08-16 · WhiteNoise for static files; media stays behind the authenticated view

**What:** WhiteNoise serves `STATIC_ROOT` from the application process, with
`CompressedManifestStaticFilesStorage` and `collectstatic` run at image build time.
Uploaded files are untouched by this: they are still streamed only by
`apps.assets.views.serve_file`, after a role and company check.
**Why:** the static assets here are htmx, Pico CSS and a stylesheet — kilobytes, vendored,
served a handful of times per session. A CDN or an S3 bucket for that is infrastructure to
operate, pay for and secure, in exchange for nothing measurable. Manifest storage adds the
content hash to each filename, which makes a far-future cache header safe and makes a
deploy incapable of serving new HTML with stale CSS; it also fails the build if a template
points at a static file that does not exist.
**Why media is not in this decision at all:** photos and manuals are tenant data. Any
mechanism that serves them by path — WhiteNoise, nginx, a bucket — makes them readable by
anyone who can guess a filename, which is the exact rule `CLAUDE.md` forbids. A test
asserts no URL pattern serves `MEDIA_URL`. The cost is that Django streams every photo;
that cost is the point.
**Rejected:** nginx serving `/static/` (a second component to configure on every platform,
for kilobytes); S3/CloudFront (an account, a bill and a bucket policy to get wrong);
`ManifestStaticFilesStorage` without compression (WhiteNoise's gzip and brotli variants
are free at build time).

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
