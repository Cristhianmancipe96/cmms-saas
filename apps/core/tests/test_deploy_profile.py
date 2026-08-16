"""The production settings profile, checked the way production loads it.

`config.settings_prod` cannot be tested with `override_settings`: half of what
it promises happens at import time, before Django is configured. So every test
here launches a real interpreter with a real environment and reads what it did
— which is also the only way `manage.py check --deploy` can be exercised
against a profile the test suite is not itself running under.

The promises under test (brief 11):

1. `check --deploy` reports zero issues, with nothing silenced.
2. `DEBUG=True` is impossible in this profile, not merely discouraged.
3. Deployment-specific values are required, not defaulted — a wrong SITE_URL
   ends up printed on stickers glued to machines.
4. Static files are served by WhiteNoise; media never is.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import get_resolver

BASE_DIR = Path(settings.BASE_DIR)

# A complete and valid production environment. Tests copy it and change one
# thing, so a failure names exactly which variable caused it.
#
# The secret key is long enough to satisfy security.W009 (50 characters, five
# distinct ones) and deliberately low-entropy: a realistic-looking random
# string in a public repository is a secret-scanner finding waiting to happen.
PRODUCTION_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings_prod",
    "DEBUG": "False",
    "SECRET_KEY": "deploy-check-only-not-a-real-secret-key-abcdefghijklmnop",
    "ALLOWED_HOSTS": "cmms.example.com",
    "CSRF_TRUSTED_ORIGINS": "https://cmms.example.com",
    "SITE_URL": "https://cmms.example.com",
    "EMAIL_HOST": "smtp.example.com",
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/cmms",
}


def run_in_production_profile(*args, **overrides):
    """Run `manage.py <args>` in a production environment, plus `overrides`.

    The environment is inherited so the interpreter still works, then the
    production values are layered on top. That order matters on the developer's
    machine: `.env` sets `DEBUG=True`, and django-environ's `read_env` only
    fills in variables that are not already set — so what is passed here wins.
    """
    env = {**os.environ, **PRODUCTION_ENV, **overrides}
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


class DeployCheckTests(SimpleTestCase):
    def test_the_deploy_check_reports_no_warnings(self):
        """`manage.py check --deploy` clean, and clean without silencing.

        `--fail-level WARNING` is what makes this a test rather than a report:
        by default `check` exits 0 no matter how many warnings it prints, so a
        job that merely runs it is a green tick that verifies nothing.
        """
        result = run_in_production_profile("check", "--deploy", "--fail-level", "WARNING")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        # Django reports "(N silenced)". Silencing a deploy warning is allowed
        # only with an ADR (CLAUDE.md), and there is none — so it must be zero.
        self.assertIn("no issues (0 silenced)", result.stdout + result.stderr)


class DebugIsImpossibleTests(SimpleTestCase):
    def test_debug_true_in_the_environment_refuses_to_boot(self):
        """The failure mode this prevents is a silent one.

        Ignoring `DEBUG=True` would be defensible; but then an operator who set
        it believes debugging is on, and the next person to "fix" that reaches
        for the settings file. Refusing to start says which variable is wrong.
        """
        result = run_in_production_profile("check", DEBUG="True")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEBUG", result.stderr)

    def test_debug_is_off_even_with_nothing_set(self):
        result = run_in_production_profile(
            "shell", "-c", "from django.conf import settings; print(settings.DEBUG)"
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("False", result.stdout)


class RequiredDeploymentValuesTests(SimpleTestCase):
    def test_a_plain_http_site_url_is_refused(self):
        """QR labels are printed with SITE_URL and then glued to machines.

        An http:// value produces stickers that a phone cannot open safely and
        that cannot be corrected without reprinting them, so this is caught at
        startup rather than at the printer.
        """
        result = run_in_production_profile("check", SITE_URL="http://localhost:8000")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SITE_URL", result.stderr)

    def test_smtp_without_a_host_is_refused(self):
        """Silence is the worst outcome for email.

        With SMTP configured but no host, Django raises per message and the
        work-order PDF someone is waiting for simply never arrives. Choosing
        the console backend on purpose is still allowed — see the next test.
        """
        result = run_in_production_profile("check", EMAIL_HOST="")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EMAIL_HOST", result.stderr)

    def test_the_console_backend_can_still_be_chosen_deliberately(self):
        result = run_in_production_profile(
            "check",
            EMAIL_HOST="",
            EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)


class StaticAndMediaTests(SimpleTestCase):
    def test_whitenoise_runs_immediately_after_the_security_middleware(self):
        """Order is the whole correctness of WhiteNoise.

        Ahead of SecurityMiddleware, static URLs skip the HTTPS redirect.
        Behind session and auth middleware, every CSS file costs a database
        query. Neither shows up as an error — only as insecure or slow.
        """
        result = run_in_production_profile(
            "shell",
            "-c",
            "from django.conf import settings; print('|'.join(settings.MIDDLEWARE))",
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        middleware = result.stdout.strip().splitlines()[-1].split("|")
        security = middleware.index("django.middleware.security.SecurityMiddleware")
        self.assertEqual(
            middleware[security + 1], "whitenoise.middleware.WhiteNoiseMiddleware"
        )

    def test_no_url_pattern_serves_media_directly(self):
        """Uploaded files are tenant data (CLAUDE.md).

        They are streamed by `apps.assets.views.serve_file`, which runs after a
        role and company check. A `static()` helper for MEDIA_URL — the usual
        one-line addition to a urls.py — would make every upload readable by
        anyone who can guess a filename, so its absence is asserted.
        """
        patterns = get_resolver().url_patterns
        media_prefix = settings.MEDIA_URL.strip("/")

        for pattern in patterns:
            self.assertFalse(
                str(pattern.pattern).strip("^/").startswith(media_prefix),
                msg=f"{pattern.pattern!r} sirve MEDIA_URL directamente",
            )
