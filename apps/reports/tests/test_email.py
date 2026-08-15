"""Sending a document, and what gets written down when it works or doesn't.

The locmem backend stands in for SMTP; the failure path is a raise from
`EmailMessage.send`, which is what a dead relay looks like from here. Both
paths end in a `NotificationLog` row — a log that only records the successes
answers the easy question.
"""

from smtplib import SMTPException
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.reports import documents
from apps.reports.models import NotificationLog
from apps.reports.tests.factories import executed_work_order

FAKE_PDF = b"%PDF-1.7\nfake bytes\n%%EOF"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Vectron <no-reply@vectron.test>",
)
class SendAssetRecordTests(TestCase):
    def setUp(self):
        patcher = mock.patch.object(
            documents.Document, "render_pdf", autospec=True, return_value=FAKE_PDF
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.company = CompanyFactory(name="Alimentos del Valle S.A.S.")
        self.asset = AssetFactory(company=self.company, code="FLOW-07", name="Empacadora 7")
        self.supervisor = SupervisorUserFactory(
            company=self.company, email="super@valle.com", first_name="Beto"
        )
        self.colleague = TechnicianUserFactory(company=self.company, email="ana@valle.com")
        self.client.force_login(self.supervisor)
        self.url = reverse("asset_record_send", args=[self.asset.pk])

    def _post(self, recipients):
        return self.client.post(self.url, {"recipients": [user.pk for user in recipients]})

    def test_it_attaches_the_pdf_and_writes_the_log_row(self):
        response = self._post([self.supervisor])

        assert response.status_code == 302
        assert response["Location"] == reverse("asset_detail", args=[self.asset.pk])

        message = mail.outbox[0]
        assert message.to == ["super@valle.com"]
        assert "FLOW-07" in message.subject
        assert "Empacadora 7" in message.body
        assert message.attachments == [
            ("hoja-de-vida-FLOW-07.pdf", FAKE_PDF, "application/pdf")
        ]

        row = NotificationLog.objects.unscoped().get()
        assert row.company_id == self.company.pk
        assert row.channel == NotificationLog.Channel.EMAIL
        assert row.kind == NotificationLog.Kind.ASSET_RECORD
        assert row.status == NotificationLog.Status.SENT
        assert row.recipient == "super@valle.com"
        assert row.asset_id == self.asset.pk
        assert row.work_order_id is None
        assert row.sent_by_id == self.supervisor.pk
        assert row.error_detail == ""

    def test_each_recipient_gets_their_own_message_and_their_own_row(self):
        self._post([self.supervisor, self.colleague])

        assert len(mail.outbox) == 2
        assert sorted(message.to[0] for message in mail.outbox) == [
            "ana@valle.com",
            "super@valle.com",
        ]
        # One address per envelope: a technician must not learn the
        # supervisor's address from the To: line of a report.
        assert all(len(message.to) == 1 for message in mail.outbox)
        assert NotificationLog.objects.unscoped().count() == 2

    def test_nobody_outside_the_company_can_be_chosen(self):
        outsider = AdminUserFactory(company=CompanyFactory(), email="fuera@otra.com")

        response = self._post([outsider])

        assert response.status_code == 200
        assert "no pertenece a tu empresa" in response.content.decode()
        assert mail.outbox == []
        assert NotificationLog.objects.unscoped().count() == 0

    def test_choosing_nobody_is_refused(self):
        response = self.client.post(self.url, {})

        assert response.status_code == 200
        assert "Elige al menos una persona" in response.content.decode()
        assert mail.outbox == []

    def test_a_dead_smtp_server_logs_the_failure_and_says_so_in_spanish(self):
        with mock.patch.object(
            mail.EmailMessage, "send", side_effect=SMTPException("conexión rechazada")
        ):
            response = self.client.post(
                self.url, {"recipients": [self.supervisor.pk]}, follow=True
            )

        assert response.status_code == 200
        content = response.content.decode()
        assert "No se pudo enviar el correo" in content

        row = NotificationLog.objects.unscoped().get()
        assert row.status == NotificationLog.Status.FAILED
        assert row.recipient == "super@valle.com"
        assert "conexión rechazada" in row.error_detail


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SendWorkOrderReportTests(TestCase):
    def setUp(self):
        patcher = mock.patch.object(
            documents.Document, "render_pdf", autospec=True, return_value=FAKE_PDF
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company, code="FLOW-09")
        self.supervisor = SupervisorUserFactory(company=self.company, email="jefe@valle.com")
        self.work_order = executed_work_order(company=self.company, asset=self.asset)
        self.client.force_login(self.supervisor)

    def test_the_row_points_at_the_work_order_and_its_equipment(self):
        response = self.client.post(
            reverse("workorder_report_send", args=[self.work_order.pk]),
            {"recipients": [self.supervisor.pk]},
        )

        assert response.status_code == 302
        message = mail.outbox[0]
        assert f"#{self.work_order.pk}" in message.subject
        assert "informe" in message.body.lower()
        assert message.attachments[0][0] == f"informe-ot-{self.work_order.pk}-FLOW-09.pdf"

        row = NotificationLog.objects.unscoped().get()
        assert row.kind == NotificationLog.Kind.WORK_ORDER_REPORT
        assert row.work_order_id == self.work_order.pk
        assert row.asset_id == self.asset.pk


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InvitedUserPasswordTests(TestCase):
    """Brief 07 carry-over from 01: the temporary password leaves by email and
    is never painted on a screen again."""

    def setUp(self):
        self.company = CompanyFactory(name="Alimentos del Valle S.A.S.")
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)
        self.url = reverse("user_invite")
        self.payload = {
            "username": "nuevo",
            "email": "nuevo@valle.com",
            "first_name": "Nora",
            "last_name": "Peña",
            "role": "technician",
            "whatsapp_phone": "",
        }

    def test_the_password_goes_to_the_new_user_and_never_to_the_screen(self):
        response = self.client.post(self.url, self.payload, follow=True)
        content = response.content.decode()

        from apps.accounts.models import User

        user = User.objects.get(username="nuevo")
        message = mail.outbox[0]
        assert message.to == ["nuevo@valle.com"]
        assert "Contraseña temporal:" in message.body

        temp_password = message.body.split("Contraseña temporal:")[1].split("\n")[0].strip()
        assert user.check_password(temp_password)
        assert temp_password not in content
        assert "Le enviamos la contraseña temporal a nuevo@valle.com" in content

        row = NotificationLog.objects.unscoped().get()
        assert row.kind == NotificationLog.Kind.TEMP_PASSWORD
        assert row.status == NotificationLog.Status.SENT
        assert row.recipient == "nuevo@valle.com"
        assert temp_password not in row.subject
        assert temp_password not in row.error_detail

    def test_an_undeliverable_invitation_creates_no_user_at_all(self):
        """An account whose only password went nowhere is a dead seat."""
        from apps.accounts.models import User

        with mock.patch.object(
            mail.EmailMessage, "send", side_effect=SMTPException("relay caído")
        ):
            response = self.client.post(self.url, self.payload, follow=True)

        assert response.status_code == 200
        assert "el usuario no se creó" in response.content.decode()
        assert not User.objects.filter(username="nuevo").exists()

        row = NotificationLog.objects.unscoped().get()
        assert row.status == NotificationLog.Status.FAILED
        assert "relay caído" in row.error_detail

    def test_an_invitation_without_an_email_is_refused(self):
        response = self.client.post(self.url, {**self.payload, "email": ""})

        assert response.status_code == 200
        assert mail.outbox == []
