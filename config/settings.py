"""
Django settings for the cmms-saas project.

Settings are read from environment variables (see .env.example) via django-environ.
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


# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
