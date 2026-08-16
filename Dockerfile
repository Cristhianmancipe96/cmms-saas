# Vectron Management — production image (brief 11).
#
# One image, three targets: a VPS with `docker run`, Railway/Render (both build
# a Dockerfile straight from the repo), and CI, which builds it on every push so
# a broken image is found here and not during a deploy. See docs/deploy.md.
#
# It contains NO secrets. Everything environment-specific arrives at run time as
# environment variables; the placeholder values in the collectstatic step below
# exist only because Django refuses to import settings without them, and are
# gone by the time the container runs.

FROM python:3.12-slim-bookworm

# - libpango / libharfbuzz: WeasyPrint draws text through Pango, which is a
#   system library and not a wheel. Without these the PDF views degrade to a
#   Spanish error message instead of a work-order report (brief 07).
# - fonts-dejavu-core: a slim image ships NO fonts at all. Pango would then
#   render every PDF in whatever fontconfig scraped together — the document is
#   produced, so nothing errors, it just comes out wrong. DejaVu Sans is the
#   second family in static/css/vectron-pdf.css (the first, Segoe UI, exists
#   only on the Windows machine the CSS was written on).
# - libpq5: PostgreSQL client library used by psycopg.
# - postgresql-client: pg_dump/psql, so a backup can be taken from inside the
#   running container when the host has no Postgres tooling (docs/deploy.md).
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
        fonts-dejavu-core \
        libpq5 \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# uv resolves from uv.lock, so the image gets the exact versions CI tested.
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings_prod

WORKDIR /app

# Dependencies first: this layer is rebuilt only when the lock file changes, so
# ordinary code edits rebuild in seconds. `--no-dev` keeps pytest, ruff and the
# rest of the toolchain out of the production image.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

# Hashed, compressed static files (WhiteNoise manifest storage). These values
# are throwaway build-time placeholders — not secrets, not used at run time —
# and exist only so the settings module imports. The build fails here if a
# template references a static file that does not exist, which is the point.
RUN DEBUG=False \
    SECRET_KEY=build-time-placeholder-overwritten-at-runtime-0123456789 \
    ALLOWED_HOSTS=build.invalid \
    CSRF_TRUSTED_ORIGINS=https://build.invalid \
    SITE_URL=https://build.invalid \
    EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend \
    DATABASE_URL=postgresql://build:build@localhost:5432/build \
    python manage.py collectstatic --noinput --clear

# Uploaded files (photos, manuals) are tenant data. The directory belongs to
# the app user so uploads work without granting write access to the code.
#
# On a platform with an ephemeral filesystem this path MUST be a mounted
# volume, or every redeploy silently loses the uploads — see docs/deploy.md.
#
# chmod on the entrypoint is belt and braces: the file is committed executable,
# but the repo is developed on Windows and a lost permission bit would only
# show up as a container that refuses to start.
#
# /app/backups exists and belongs to the app user for the same reason: the
# container runs as vectron, and scripts/backup.sh cannot write into a
# root-owned directory. Mount a volume there, or the dumps go away with the
# container — see docs/deploy.md.
RUN useradd --create-home --uid 10001 vectron \
    && mkdir -p /app/media /app/backups \
    && chmod +x /app/docker-entrypoint.sh \
    && chown -R vectron:vectron /app/media /app/backups /app/staticfiles

# Never root: a bug that reaches the shell should not also own the filesystem.
USER vectron

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
