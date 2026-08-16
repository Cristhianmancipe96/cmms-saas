from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.core.models import BootstrapPing
from apps.core.tests.factories import BootstrapPingFactory


class ProjectConfigTests(TestCase):
    def test_default_database_is_postgresql(self):
        assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"

    def test_locale_and_timezone_for_colombia(self):
        assert settings.LANGUAGE_CODE == "es-co"
        assert settings.TIME_ZONE == "America/Bogota"


class BootstrapPingModelTests(TestCase):
    def test_model_round_trips_against_postgres(self):
        BootstrapPingFactory(note="hola")

        ping = BootstrapPing.objects.get(note="hola")

        assert ping.note == "hola"
        assert ping.created_at is not None


class HomeViewTests(TestCase):
    """Brief 01's "deny by default" rule (CLAUDE.md) applies to `/` too: it's
    the documented post-login landing page, not a public page.
    """

    def test_anonymous_is_redirected_to_login(self):
        response = Client().get("/")

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))

    def test_authenticated_user_lands_on_their_own_starting_points(self):
        user = UserFactory()  # a technician
        client = Client()
        client.force_login(user)

        response = client.get("/")
        page = response.content.decode()

        assert response.status_code == 200
        assert user.company.name in page
        assert "Mis OTs" in page
        # Brief 10 polish: the landing page offers what this role can act on.
        # A technician has no dashboard (no company-wide KPIs on a plant-floor
        # phone), exactly as base.html's nav decides.
        assert reverse("kpi_dashboard") not in page
