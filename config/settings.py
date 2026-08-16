"""
Base Django settings for the cmms-saas project.

Settings are read from environment variables (see .env.example) via django-environ.

This module is the development and test profile. Production does NOT use it
directly: it runs `config.settings_prod`, which imports everything here and then
locks down the parts that only matter once the site is reachable from the
internet (brief 11). See docs/deploy.md.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env.str("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# The public base URL printed into every QR label (brief 06). Configuration,
# not `request.build_absolute_uri`: a sticker glued to a machine outlives the
# request that generated it, and must point at the deployment the plant
# actually uses — not at whichever host (proxy, LAN IP, localhost) happened to
# render the label sheet.
SITE_URL = env.str("SITE_URL", default="http://localhost:8000")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "apps.core",
    "apps.accounts",
    "apps.assets",
    "apps.checklists",
    "apps.maintenance",
    "apps.workorders",
    "apps.reports",
    "apps.requests_",
    "apps.audit",
    "apps.kpis",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.CurrentCompanyMiddleware",
    "apps.core.middleware.SuspensionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": env.db("DATABASE_URL"),
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "es-co"

TIME_ZONE = "America/Bogota"

USE_I18N = True

USE_TZ = True


# Static & media files
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


# Email (brief 07)
# https://docs.djangoproject.com/en/5.2/topics/email/
#
# The default backend prints to the console instead of sending: a developer who
# never sets EMAIL_* gets a visible message in the terminal rather than silent
# nothing. Production sets EMAIL_BACKEND to the SMTP one (Gmail, Resend, ...).

EMAIL_BACKEND = env.str(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = env.str("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
# Not optional: without it a dead SMTP host holds the worker until the OS gives
# up, which turns "el correo no salió" into "la aplicación se congeló".
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=20)
DEFAULT_FROM_EMAIL = env.str(
    "DEFAULT_FROM_EMAIL", default="Vectron Management <no-reply@vectron.local>"
)

# n8n webhook (brief 08)
#
# All three are optional and the product is fully functional with none of them
# set — that is the rule, not a convenience: PLAN §7 says a dead n8n must not
# take the CMMS with it, and "not configured" is the same code path as "not
# answering" (apps/core/webhooks.py). The token is a secret and lives only in
# the environment; it travels in a header, never in a payload and never in a
# log line.
#
# The timeout is short and paid on a background thread, so even a black-holed
# endpoint costs the operator nothing.

N8N_WEBHOOK_URL = env.str("N8N_WEBHOOK_URL", default="")
N8N_WEBHOOK_TOKEN = env.str("N8N_WEBHOOK_TOKEN", default="")
N8N_WEBHOOK_TIMEOUT = env.float("N8N_WEBHOOK_TIMEOUT", default=3.0)


# Logging (brief 11)
#
# One handler, stdout, everywhere. On a VPS or a PaaS the platform is what
# collects logs: it reads the process's stdout and nothing else. Writing to a
# file inside a container means the lines die with the container, so the
# `logger.warning` calls in apps/core/webhooks.py — the ones that say a webhook
# could not be delivered — would be invisible exactly when they matter.
#
# The format is fixed and parseable (timestamp, level, logger, message) instead
# of Django's bare message, so a line in the platform's log viewer says *when*
# and *who* without having to guess.
#
# House rule: no PII and no credentials in log lines (CLAUDE.md). The webhook
# logger already obeys it — it logs the exception class, never the payload.

LOG_LEVEL = env.str("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        # Django logs handled 4xx at WARNING and unhandled 500s at ERROR here.
        # Left at INFO so a burst of 404s on the QR endpoint is visible.
        "django.request": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Error tracking (phase 3) — deliberately not wired yet.
#
# When it is: add `sentry-sdk` to the dependencies and initialise it here with
# `SENTRY_DSN` from the environment, `send_default_pii=False` (Ley 1581: the
# tracker is a third party and must not receive customer data) and a traces
# sample rate well below 1.0. Until then the platform's log viewer is the only
# place errors surface, which is why the format above is worth having.


# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
