"""The auditor's screen: who may open it, and what it is allowed to show them."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.audit.models import AuditLog
from apps.audit.tests.factories import AuditLogFactory
from apps.requests_.models import MaintenanceRequest
from apps.workorders.models import WorkOrder


class AccessTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.url = reverse("auditlog_list")

    def test_an_admin_opens_it(self):
        self.client.force_login(AdminUserFactory(company=self.company))

        assert self.client.get(self.url).status_code == 200

    def test_a_supervisor_does_not(self):
        """Admin only, as the brief specifies: the log records what supervisors
        do, so reading it is not their own privilege to hold."""
        self.client.force_login(SupervisorUserFactory(company=self.company))

        assert self.client.get(self.url).status_code == 403

    def test_a_technician_does_not(self):
        self.client.force_login(TechnicianUserFactory(company=self.company))

        assert self.client.get(self.url).status_code == 403

    def test_staff_does_not(self):
        self.client.force_login(StaffUserFactory(company=self.company))

        assert self.client.get(self.url).status_code == 403

    def test_an_anonymous_visitor_is_sent_to_the_login_page(self):
        response = self.client.get(self.url)

        assert response.status_code == 302
        assert reverse("login") in response.url

    def test_the_nav_offers_it_only_to_admins(self):
        self.client.force_login(SupervisorUserFactory(company=self.company))
        supervisor_home = self.client.get(reverse("home")).content.decode()

        self.client.force_login(AdminUserFactory(company=self.company))
        admin_home = self.client.get(reverse("home")).content.decode()

        assert self.url not in supervisor_home
        assert self.url in admin_home


class IsolationTests(TestCase):
    def test_an_admin_never_sees_another_companys_rows(self):
        company_a = CompanyFactory(name="Empresa A")
        company_b = CompanyFactory(name="Empresa B")
        AuditLogFactory(company=company_a, object_repr="OT #1 de la empresa A")
        AuditLogFactory(company=company_b, object_repr="OT #1 de la empresa B")
        self.client.force_login(AdminUserFactory(company=company_b))

        body = self.client.get(reverse("auditlog_list")).content.decode()

        assert "OT #1 de la empresa B" in body
        assert "OT #1 de la empresa A" not in body

    def test_the_user_filter_only_lists_colleagues(self):
        """`User` is not a company-scoped model, so this dropdown had to be
        filtered by hand — a list of names is customer data too."""
        company_a = CompanyFactory()
        company_b = CompanyFactory()
        stranger = TechnicianUserFactory(company=company_a, username="ajeno")
        self.client.force_login(AdminUserFactory(company=company_b, username="propio"))

        body = self.client.get(reverse("auditlog_list")).content.decode()

        assert "propio" in body
        assert stranger.username not in body


class FilterTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.admin = AdminUserFactory(company=self.company)
        self.other = SupervisorUserFactory(company=self.company)
        self.client.force_login(self.admin)
        self.url = reverse("auditlog_list")

        self.mine = AuditLogFactory(
            company=self.company,
            user=self.admin,
            action=AuditLog.Action.UPDATE,
            model_label="assets.Asset",
            object_repr="EQUIPO EDITADO",
        )
        self.theirs = AuditLogFactory(
            company=self.company,
            user=self.other,
            action=AuditLog.Action.TRANSITION,
            model_label="workorders.WorkOrder",
            object_repr="OT MOVIDA",
        )

    def test_filtering_by_user(self):
        body = self.client.get(self.url, {"usuario": self.other.pk}).content.decode()

        assert "OT MOVIDA" in body
        assert "EQUIPO EDITADO" not in body

    def test_filtering_by_action(self):
        body = self.client.get(
            self.url, {"accion": AuditLog.Action.TRANSITION}
        ).content.decode()

        assert "OT MOVIDA" in body
        assert "EQUIPO EDITADO" not in body

    def test_filtering_by_model(self):
        body = self.client.get(self.url, {"modelo": "assets.Asset"}).content.decode()

        assert "EQUIPO EDITADO" in body
        assert "OT MOVIDA" not in body

    def test_filtering_by_date_range(self):
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()

        empty = self.client.get(self.url, {"desde": tomorrow}).content.decode()
        today = self.client.get(
            self.url, {"desde": timezone.localdate().isoformat()}
        ).content.decode()

        assert "EQUIPO EDITADO" not in empty
        assert "EQUIPO EDITADO" in today

    def test_a_nonsense_date_is_ignored_rather_than_a_500(self):
        response = self.client.get(self.url, {"desde": "ayer por la tarde"})

        assert response.status_code == 200
        assert "EQUIPO EDITADO" in response.content.decode()


class EndToEndTraceTests(TestCase):
    """The brief's exit criterion, on the screen an admin actually opens:
    «encuentra quién reportó, quién convirtió y cuándo»."""

    def test_the_admin_reads_the_whole_story_of_one_failure(self):
        company = CompanyFactory()
        asset = AssetFactory(company=company, code="COMP-01")
        reporter = StaffUserFactory(company=company, username="ana_oficina")
        supervisor = SupervisorUserFactory(company=company, username="beto_super")
        admin = AdminUserFactory(company=company)

        self.client.force_login(reporter)
        self.client.post(
            reverse("maintenancerequest_create", args=[asset.pk]),
            {"description": "La banda se detiene sola."},
        )
        request_obj = MaintenanceRequest.objects.unscoped().get()

        self.client.force_login(supervisor)
        self.client.post(
            reverse("maintenancerequest_convert", args=[request_obj.pk]),
            {"priority": WorkOrder.Priority.ALTA},
        )

        self.client.force_login(admin)
        body = self.client.get(
            reverse("auditlog_list"), {"modelo": "requests.MaintenanceRequest"}
        ).content.decode()

        work_order = WorkOrder.objects.unscoped().get()
        assert "ana_oficina" in body        # quién reportó
        assert "beto_super" in body         # quién convirtió
        assert f"Solicitud #{request_obj.pk} · COMP-01" in body
        assert "convertida" in body
        assert str(work_order.pk) in body
        # …y cuándo: the rows carry the date they were written.
        assert timezone.localdate().strftime("%d/%m/%Y") in body
