"""Prove that SMTP works on this deployment, before a customer discovers it does not.

    python manage.py send_test_email --to alguien@dominio.com

Email is the one integration that fails silently by design: the application is
fail-safe about it (a dead SMTP server must never take a work order down), so
"no llegó el correo" produces no error anywhere the operator looks. This
command turns that silence into an exit code and a Spanish diagnosis.

It sends a real message through whatever backend the running settings use, so
it is worth running once per deployment — it is step 4 of the smoke test in
docs/deploy.md.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

# What each failure actually means, in the operator's words. Mapping on the
# exception class name keeps this readable without importing smtplib's tree.
DIAGNOSES = {
    "SMTPAuthenticationError": (
        "el servidor rechazó el usuario o la contraseña. Con Gmail hay que usar "
        "una contraseña de aplicación, no la del correo."
    ),
    "SMTPSenderRefused": (
        "el servidor no acepta ese remitente. DEFAULT_FROM_EMAIL debe ser una "
        "dirección que el proveedor tenga verificada."
    ),
    "SMTPRecipientsRefused": "el servidor rechazó al destinatario.",
    "SMTPConnectError": "no se pudo conectar. Revise EMAIL_HOST y EMAIL_PORT.",
    "SMTPServerDisconnected": (
        "el servidor cortó la conexión. Suele ser EMAIL_PORT o EMAIL_USE_TLS mal "
        "puestos (587 con TLS, 465 con SSL)."
    ),
    "gaierror": "no se pudo resolver EMAIL_HOST: revise que el nombre esté bien escrito.",
    "timeout": (
        "el servidor no respondió antes de EMAIL_TIMEOUT segundos. Puede ser un "
        "firewall del proveedor bloqueando el puerto de salida."
    ),
    "TimeoutError": (
        "el servidor no respondió antes de EMAIL_TIMEOUT segundos. Puede ser un "
        "firewall del proveedor bloqueando el puerto de salida."
    ),
}


class Command(BaseCommand):
    help = "Envía un correo de prueba para verificar la configuración SMTP."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            required=True,
            help="Dirección a la que enviar el correo de prueba.",
        )

    def handle(self, *args, **options):
        recipient = options["to"]

        # The host and the user are configuration and safe to show; the
        # password is a secret and is never printed, not even partially
        # (CLAUDE.md: no credentials in logs).
        self.stdout.write(f"Backend:   {settings.EMAIL_BACKEND}")
        self.stdout.write(f"Servidor:  {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
        self.stdout.write(f"Usuario:   {settings.EMAIL_HOST_USER or '(sin usuario)'}")
        self.stdout.write(f"Remitente: {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"Enviando a {recipient}...")

        try:
            sent = send_mail(
                subject="Vectron Management — correo de prueba",
                message=(
                    "Si está leyendo esto, el envío de correo de esta instalación "
                    "de Vectron Management funciona.\n\n"
                    "Los informes de órdenes de trabajo y las fichas de equipo en "
                    "PDF salen por este mismo camino."
                ),
                from_email=None,  # DEFAULT_FROM_EMAIL
                recipient_list=[recipient],
                # Deliberately not fail_silently: the entire point of this
                # command is to surface the error the application swallows.
                fail_silently=False,
            )
        except Exception as error:  # noqa: BLE001 — reported, not handled
            name = type(error).__name__
            diagnosis = DIAGNOSES.get(name, "revise las variables EMAIL_* del entorno.")
            raise CommandError(f"No se pudo enviar ({name}): {diagnosis}") from error

        if not sent:
            raise CommandError(
                "El backend no reportó ningún correo enviado. Revise EMAIL_BACKEND."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Correo entregado al servidor. Revise la bandeja de {recipient} "
                "(y la carpeta de spam la primera vez)."
            )
        )
