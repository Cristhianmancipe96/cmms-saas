# Brief 00 — Bootstrap: Django skeleton, Postgres, CI, first push

**Depends on:** nothing (first brief).
**Goal:** a running, tested, linted, public repository any later brief can build on.

## Build

1. **Git + GitHub first.** If the repo has no git history yet: `git init -b main`, first
   commit of the existing scaffold, create the **public** GitHub repo `cmms-saas` and
   push (`gh repo create cmms-saas --public --source . --push`). If `gh` isn't
   authenticated, pause and tell the owner exactly what to run.
2. **Project layout** with `uv`: `pyproject.toml` (Python 3.12, Django 5, `psycopg[binary]`,
   `django-environ`, `django-htmx`; dev: pytest, pytest-django, factory-boy, ruff,
   pre-commit). Commit `uv.lock`.
3. Django project `config/` + apps package `apps/` + first app `apps/core`.
   Settings read from env (`DATABASE_URL`, `SECRET_KEY`, `DEBUG`); `TIME_ZONE=
   "America/Bogota"`, `LANGUAGE_CODE="es-co"`, media/static configured. `.env.example`.
4. **`docker-compose.yml`**: `db` service (postgres:16, healthcheck, volume). Document in
   README: if the owner's machine has no Docker, use a free Neon/Supabase Postgres and
   set `DATABASE_URL` — SQLite is not an option.
5. **Base template**: mobile-first layout, vendored `htmx.min.js` + Pico CSS in
   `static/vendor/`, Spanish shell (title "Mantenimiento"), `{% block content %}`,
   nav placeholder, Django messages rendering.
6. **pytest** wired (`DJANGO_SETTINGS_MODULE`, db reuse) + one smoke test: a model
   round-trip against Postgres and a 200 from `/` (temporary "hola" view is fine).
7. **CI**: GitHub Actions workflow — postgres service container, `uv sync`,
   `ruff check .`, `pytest`. Badge in README.
8. **pre-commit** config already exists — install hooks and verify gitleaks runs.

## Out of scope

Any business model, auth flows, HTMX interactions beyond the base template.

## Acceptance criteria

1. Fresh clone + `docker compose up -d db` + `uv sync` + `uv run pytest -q` → green.
2. CI is green on GitHub on `main`, publicly visible.
3. `ruff check .` clean; pre-commit (incl. gitleaks) passes.
4. `.env` is git-ignored; `.env.example` documents every variable; no secret anywhere.
5. `TIME_ZONE`, `LANGUAGE_CODE` and Postgres-only config verified by a test asserting
   `settings.DATABASES` engine is postgresql.

## Definition of done

Per CLAUDE.md. Commit: `chore(bootstrap): django skeleton, postgres, CI and tooling`.
