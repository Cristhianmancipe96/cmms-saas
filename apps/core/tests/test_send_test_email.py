"""The command that answers "¿por qué no llegó el correo?".

The application is fail-safe about email on purpose, so the only thing that can
report an SMTP problem is a command asked to do it. These tests cover the two
outcomes an operator sees: a message that left, and an error that names what to
fix without ever printing the password.
"""

from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST="smtp.example.com",
    EMAIL_HOST_USER="cuenta@example.com",
    EMAIL_HOST_PASSWORD="una-contrasena-que-no-debe-salir",
    DEFAULT_FROM_EMAIL="Vectron <no-reply@example.com>",
)
class SendTestEmailTests(SimpleTestCase):
    def test_it_sends_to_the_given_address(self):
        out = StringIO()

        call_command("send_test_email", to="jefe@empresa.com", stdout=out)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["jefe@empresa.com"])
        self.assertEqual(mail.outbox[0].from_email, "Vectron <no-reply@example.com>")

    def test_it_never_prints_the_password(self):
        """The output is meant to be pasted into a chat when asking for help."""
        out = StringIO()

        call_command("send_test_email", to="jefe@empresa.com", stdout=out)

        self.assertNotIn("una-contrasena-que-no-debe-salir", out.getvalue())
        self.assertIn("smtp.example.com", out.getvalue())

    def test_an_smtp_failure_becomes_an_error_with_a_diagnosis(self):
        """A traceback tells a developer what broke; this tells the owner what to change."""
        failure = type("SMTPAuthenticationError", (Exception,), {})

        with mock.patch(
            "apps.core.management.commands.send_test_email.send_mail",
            side_effect=failure("535"),
        ):
            with self.assertRaises(CommandError) as caught:
                call_command("send_test_email", to="jefe@empresa.com", stdout=StringIO())

        self.assertIn("contraseña de aplicación", str(caught.exception))

    def test_a_backend_that_sends_nothing_is_an_error(self):
        """`send_mail` returning 0 is not success — it is a message that vanished."""
        with mock.patch(
            "apps.core.management.commands.send_test_email.send_mail", return_value=0
        ):
            with self.assertRaises(CommandError):
                call_command("send_test_email", to="jefe@empresa.com", stdout=StringIO())
