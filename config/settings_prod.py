"""
Production settings — the profile used by every internet-facing deployment.

Run with `DJANGO_SETTINGS_MODULE=config.settings_prod` (the Dockerfile sets it).
Everything in `config.settings` still applies; this module only tightens what
changes when the site stops being localhost. See docs/deploy.md for the deploy
procedure and docs/DECISIONS.md for why the split looks like this.

Two rules shape this file:

1. **`DEBUG=True` must be impossible here, not merely unlikely.** It is a
   literal below — no environment variable can flip it — and an operator who
   sets `DEBUG=True` in the environment gets a refusal to boot instead of a
   silently ignored variable. A production `DEBUG=True` leaks the settings, the
   SQL and the traceback of every error to whoever triggers it.
2. **Everything deployment-specific is required, not defaulted.** A missing
   `ALLOWED_HOSTS` or `SITE_URL` fails at startup with a named variable. The
   alternative — a default that "works" — is how a QR sticker ends up pointing
   at http://localhost:8000 on a machine in a plant.
"""

from django.core.exceptions import ImproperlyConfigured

from config.settings import *  # noqa: F403

# --------------------------------------------------------------------------
# Debug: off, and not negotiable
# --------------------------------------------------------------------------

DEBUG = False

if env.bool("DEBUG", default=False):  # noqa: F405
    raise ImproperlyConfigured(
        "DEBUG=True está puesto en el entorno y este es el perfil de producción. "
        "Quite la variable DEBUG (o póngala en False) antes de desplegar."
    )


# --------------------------------------------------------------------------
# Where this deployment lives
# --------------------------------------------------------------------------

# No default on purpose: Django's own default of [] would answer every Host
# header once DEBUG is False, and a default of ["*"] hands the site to anyone
# who points a domain at the server.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")  # noqa: F405

# Django only accepts a POST when the Origin matches a trusted origin, and
# behind a reverse proxy the scheme it reconstructs may not match. Required
# rather than defaulted because getting it wrong looks like "el login no
# funciona", not like a configuration error. Full origins, with scheme:
# https://cmms.midominio.com
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")  # noqa: F405

# The base URL burned into printed QR labels (brief 06). In production it must
# be the public HTTPS URL: the whole point of the QR is that a prospect scans
# it with their own phone, off the company network. A sticker cannot be edited
# after it is glued to a machine, so a wrong value here is expensive.
SITE_URL = env.str("SITE_URL").rstrip("/")  # noqa: F405

if not SITE_URL.startswith("https://"):
    raise ImproperlyConfigured(
        f"SITE_URL debe empezar por https:// en producción (está en {SITE_URL!r}). "
        "Las etiquetas QR se imprimen con esta URL y se escanean desde celulares "
        "fuera de la red de la empresa."
    )


# --------------------------------------------------------------------------
# HTTPS
# --------------------------------------------------------------------------

SECURE_SSL_REDIRECT = True

# HSTS tells the browser to refuse plain HTTP for this host for N seconds. It
# is deliberately started SHORT: while the domain and the certificate are being
# settled, a mistake is undone by waiting out the window instead of by
# unreachable-site support calls.
#
# The ramp, once HTTPS has been stable for a few days each step:
#   3600 (1 h, the default here) -> 86400 (1 día) -> 2592000 (30 días)
#   -> 31536000 (1 año, el valor definitivo)
# Raise it with the SECURE_HSTS_SECONDS environment variable; no code change.
#
# Only after a year's worth of max-age has been served does submitting the
# domain at https://hstspreload.org make sense — the preload directive below is
# a claim the list itself verifies, and it rejects short max-age values.
#
# INCLUDE_SUBDOMAINS is the reason to keep the window short at first: it covers
# every subdomain of the deployment, including any that is still on plain HTTP.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# TLS almost always terminates at a reverse proxy (Railway's router, nginx,
# Caddy), so Django sees a plain HTTP request and — with SECURE_SSL_REDIRECT on
# — would redirect it to itself forever. This header is what breaks the loop.
#
# It is OFF by default because trusting X-Forwarded-Proto when the app is also
# reachable directly lets a client claim "this request was HTTPS" and defeat
# every secure-cookie and redirect rule at once. Turn it on only when a proxy
# in front of the app sets the header itself and strips any incoming copy —
# which is exactly what Railway/Render/nginx-with-`proxy_set_header` do.
if env.bool("TRUST_PROXY_SSL_HEADER", default=False):  # noqa: F405
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# --------------------------------------------------------------------------
# Cookies and headers
# --------------------------------------------------------------------------

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

CSRF_COOKIE_SECURE = True
# Nothing in this project reads the CSRF cookie from JavaScript: every mutating
# request is a form (htmx posts the form, token field included), so hiding the
# cookie from scripts costs nothing and removes one thing an XSS could read.
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
# Referers are sent to this site only. A work-order URL carries tenant
# identifiers; they have no business travelling to a third party in a header.
SECURE_REFERRER_POLICY = "same-origin"


# --------------------------------------------------------------------------
# Static files
# --------------------------------------------------------------------------

# WhiteNoise serves STATIC_ROOT straight from the app process. It must sit
# immediately after SecurityMiddleware: before it, the HTTPS redirect never
# runs for static URLs; after the session/auth middleware, every CSS file pays
# for a database session lookup. The order is asserted by a test.
MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

# Manifest storage renames each file to include a hash of its contents, so a
# far-future cache header is safe and a deploy never serves a stale mix of old
# CSS with new HTML. It also fails loudly at `collectstatic` time if a template
# references a static file that does not exist.
#
# MEDIA IS NOT HERE, and must never be: uploaded photos and documents are
# tenant data and are served only through the authorised view in
# apps/assets/views.py (CLAUDE.md). WhiteNoise only ever sees STATIC_ROOT.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------

# Development prints emails to the console; in production that would mean the
# work-order PDF a customer is waiting for lands in a log file and nowhere
# else. So the SMTP backend is the default here, and a missing host is a
# startup error rather than a silent black hole.
#
# Setting EMAIL_BACKEND explicitly to the console backend is still allowed —
# that is a decision someone made on purpose, not an oversight.
EMAIL_BACKEND = env.str(  # noqa: F405
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)

if EMAIL_BACKEND.endswith("smtp.EmailBackend") and not EMAIL_HOST:  # noqa: F405
    raise ImproperlyConfigured(
        "Falta EMAIL_HOST: el perfil de producción envía correo por SMTP. "
        "Configure EMAIL_HOST/EMAIL_HOST_USER/EMAIL_HOST_PASSWORD (ver "
        "docs/deploy.md) o ponga EMAIL_BACKEND en el backend de consola a "
        "propósito."
    )
