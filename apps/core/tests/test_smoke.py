from django.conf import settings
from django.test import Client, TestCase

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
    def test_home_returns_200(self):
        response = Client().get("/")

        assert response.status_code == 200
        assert "hola" in response.content.decode()
