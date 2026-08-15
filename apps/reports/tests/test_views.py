"""Who may reach the two documents, and what a stranger gets.

`Document.render_pdf` is stubbed in most of these: the question here is the
view's — permission, tenancy, status, headers — and answering it should not
depend on whether the machine running the suite has a print engine installed.
The engine has its own test (`test_pdf_output.py`), and the "no engine" branch
is exercised deliberately below.
"""

from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    PlatformAdminUserFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.reports import documents, pdf
from apps.reports.tests.factories import executed_work_order
from apps.workorders.models import WorkOrder
from apps.workorders.tests.factories import WorkOrderFactory

FAKE_PDF = b"%PDF-1.7\nfake bytes\n%%EOF"


class StubbedEngineMixin:
    def stub_engine(self):
        patcher = mock.patch.object(
            documents.Document, "render_pdf", autospec=True, return_value=FAKE_PDF
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class AssetRecordAccessTests(StubbedEngineMixin, TestCase):
    def setUp(self):
        self.stub_engine()
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company, code="FLOW-07")
        self.url = reverse("asset_record_pdf", args=[self.asset.pk])

    def test_every_role_in_the_company_may_download_it(self):
        for factory in (
            AdminUserFactory,
            SupervisorUserFactory,
            TechnicianUserFactory,
            StaffUserFactory,
        ):
            with self.subTest(role=factory.__name__):
                self.client.force_login(factory(company=self.company))
                response = self.client.get(self.url)

                assert response.status_code == 200
                assert response["Content-Type"] == "application/pdf"
                assert response.content == FAKE_PDF

    def test_the_file_name_says_what_it_is(self):
        self.client.force_login(StaffUserFactory(company=self.company))

        disposition = self.client.get(self.url)["Content-Disposition"]

        assert disposition == 'inline; filename="hoja-de-vida-FLOW-07.pdf"'

    def test_anonymous_is_sent_to_the_login(self):
        response = self.client.get(self.url)

        assert response.status_code == 302
        assert reverse("login") in response["Location"]

    def test_another_company_gets_404_not_403(self):
        self.client.force_login(AdminUserFactory(company=CompanyFactory()))

        assert self.client.get(self.url).status_code == 404


class WorkOrderReportAccessTests(StubbedEngineMixin, TestCase):
    def setUp(self):
        self.stub_engine()
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)

    def _url(self, work_order) -> str:
        return reverse("workorder_report_pdf", args=[work_order.pk])

    def test_a_finished_or_verified_order_has_a_report(self):
        for verified in (False, True):
            with self.subTest(verified=verified):
                work_order = executed_work_order(
                    company=self.company, asset=self.asset, verified=verified
                )
                self.client.force_login(TechnicianUserFactory(company=self.company))

                assert self.client.get(self._url(work_order)).status_code == 200

    def test_an_unfinished_order_has_no_report_yet(self):
        """404, not 403: before the work is done the document does not exist."""
        self.client.force_login(AdminUserFactory(company=self.company))
        for status in (
            WorkOrder.Status.ABIERTA,
            WorkOrder.Status.ASIGNADA,
            WorkOrder.Status.EN_PROGRESO,
            WorkOrder.Status.CANCELADA,
        ):
            with self.subTest(status=status):
                work_order = WorkOrderFactory(asset=self.asset, status=status)

                assert self.client.get(self._url(work_order)).status_code == 404

    def test_another_company_gets_404(self):
        work_order = executed_work_order(company=self.company, asset=self.asset)
        self.client.force_login(AdminUserFactory(company=CompanyFactory()))

        assert self.client.get(self._url(work_order)).status_code == 404


class SendScreenPermissionTests(StubbedEngineMixin, TestCase):
    def setUp(self):
        self.stub_engine()
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.work_order = executed_work_order(company=self.company, asset=self.asset)
        self.asset_url = reverse("asset_record_send", args=[self.asset.pk])
        self.wo_url = reverse("workorder_report_send", args=[self.work_order.pk])

    def test_supervisors_and_admins_may_open_the_send_screen(self):
        for factory in (AdminUserFactory, SupervisorUserFactory):
            with self.subTest(role=factory.__name__):
                self.client.force_login(factory(company=self.company))

                assert self.client.get(self.asset_url).status_code == 200
                assert self.client.get(self.wo_url).status_code == 200

    def test_technicians_and_staff_may_not(self):
        for factory in (TechnicianUserFactory, StaffUserFactory):
            with self.subTest(role=factory.__name__):
                self.client.force_login(factory(company=self.company))

                assert self.client.get(self.asset_url).status_code == 403
                assert self.client.post(self.asset_url, {}).status_code == 403
                assert self.client.get(self.wo_url).status_code == 403
                assert self.client.post(self.wo_url, {}).status_code == 403

    def test_a_platform_admin_has_no_company_to_send_from(self):
        self.client.force_login(PlatformAdminUserFactory())

        assert self.client.get(self.asset_url).status_code == 403

    def test_another_company_gets_404_on_the_send_screen(self):
        self.client.force_login(AdminUserFactory(company=CompanyFactory()))

        assert self.client.get(self.asset_url).status_code == 404
        assert self.client.get(self.wo_url).status_code == 404

    def test_the_picker_only_offers_colleagues(self):
        outsider = AdminUserFactory(company=CompanyFactory(), email="fuera@otra.com")
        colleague = TechnicianUserFactory(company=self.company, email="dentro@mia.com")
        self.client.force_login(AdminUserFactory(company=self.company))

        content = self.client.get(self.asset_url).content.decode()

        assert colleague.email in content
        assert outsider.email not in content


class MissingEngineTests(TestCase):
    """A server without WeasyPrint says so in Spanish. It never 500s."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        patcher = mock.patch.object(
            pdf, "_load_engine", side_effect=pdf.PdfEngineUnavailable(pdf.PDF_ENGINE_MESSAGE)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(AdminUserFactory(company=self.company))

    def test_download_falls_back_to_the_equipment_screen_with_a_message(self):
        response = self.client.get(
            reverse("asset_record_pdf", args=[self.asset.pk]), follow=True
        )

        assert response.status_code == 200
        assert response.redirect_chain[-1][0] == reverse("asset_detail", args=[self.asset.pk])
        assert "motor de impresión" in response.content.decode()

    def test_sending_stops_before_anyone_is_mailed(self):
        from django.core import mail

        from apps.reports.models import NotificationLog

        response = self.client.post(
            reverse("asset_record_send", args=[self.asset.pk]),
            {"recipients": [self.client.session["_auth_user_id"]]},
            follow=True,
        )

        assert response.status_code == 200
        assert "motor de impresión" in response.content.decode()
        assert mail.outbox == []
        assert NotificationLog.objects.unscoped().count() == 0
