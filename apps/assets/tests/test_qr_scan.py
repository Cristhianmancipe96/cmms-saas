"""The scan flow: `/e/<qr_uuid>` seen by five different people.

The tests are grouped by who is holding the phone, because that is the axis
the feature is built on. What every group is really asserting is one of two
things: this person sees what they came for, or this person sees the plate
and only the plate.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    PlatformAdminUserFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.maintenance.tests.factories import MaintenancePlanFactory
from apps.workorders.models import WorkOrder
from apps.workorders.tests.factories import AssignedWorkOrderFactory, WorkOrderFactory

PASSWORD = "testpass123"


class ScanBaseTests(TestCase):
    """One machine, one company, and the cast that scans it."""

    def setUp(self):
        self.company = CompanyFactory(name="Alimentos del Valle")
        self.asset = AssetFactory(
            company=self.company,
            code="FLOW-07",
            name="Empacadora Flowpac 7",
            location_detail="Línea 2",
        )
        self.url = reverse("asset_scan", args=[self.asset.qr_uuid])


class ScanUrlTests(ScanBaseTests):
    def test_url_is_the_uuid_and_only_the_uuid(self):
        """No pk segment, and nothing else about the machine either — a
        printed sticker is public, so the string on it says nothing.

        (Not `str(pk) not in url`: a one-digit pk collides with the UUID's
        own hex by chance. What the URL *is* proves it; what the router does
        with a pk is the test below.)
        """
        assert self.url == f"/e/{self.asset.qr_uuid}"
        assert self.asset.code not in self.url
        assert self.asset.name not in self.url

    def test_primary_key_in_the_scan_url_is_a_404(self):
        """Acceptance: the QR namespace does not accept ids at all."""
        response = self.client.get(f"/e/{self.asset.pk}")

        assert response.status_code == 404

    def test_unknown_uuid_is_404(self):
        response = self.client.get("/e/6f1c4b2a-0000-4000-8000-000000000000")

        assert response.status_code == 404

    def test_scan_url_refuses_to_be_written_to(self):
        """No write is ever born on a scanned page — enforced by the method,
        not by the absence of a form."""
        response = self.client.post(self.url, {})

        assert response.status_code == 405


class ScanAnonymousTests(ScanBaseTests):
    """No session: the plate, and nothing that is not on the physical label."""

    def test_shows_code_and_name(self):
        response = self.client.get(self.url)
        content = response.content.decode()

        assert response.status_code == 200
        assert "FLOW-07" in content
        assert "Empacadora Flowpac 7" in content

    def test_leaks_no_operational_data(self):
        AssignedWorkOrderFactory(asset=self.asset, company=self.company)
        MaintenancePlanFactory(asset=self.asset, company=self.company)

        content = self.client.get(self.url).content.decode()

        assert self.company.name not in content
        assert self.asset.site.name not in content
        assert self.asset.location_detail not in content
        assert "Operativo" not in content
        assert "Criticidad" not in content
        assert "Órdenes" not in content
        assert "Historial" not in content

    def test_offers_no_link_carrying_the_primary_key(self):
        content = self.client.get(self.url).content.decode()

        assert f"/equipos/{self.asset.pk}/" not in content

    def test_login_link_comes_back_here(self):
        content = self.client.get(self.url).content.decode()

        assert f'href="{reverse("login")}?next={self.url}"' in content

    def test_login_lands_on_the_machine_the_technician_scanned(self):
        """The whole point of the flow: scan, log in, and be standing in front
        of the same machine — not on the home page."""
        technician = TechnicianUserFactory(company=self.company)
        AssignedWorkOrderFactory(
            asset=self.asset, company=self.company, assigned_to=technician
        )

        response = self.client.post(
            reverse("login"),
            {"username": technician.username, "password": PASSWORD, "next": self.url},
            follow=True,
        )

        assert response.redirect_chain[-1][0] == self.url
        assert "Tus OTs en este equipo" in response.content.decode()


class ScanTechnicianTests(ScanBaseTests):
    """Their work on this machine, with the execution screen one tap away."""

    def setUp(self):
        super().setUp()
        self.technician = TechnicianUserFactory(company=self.company)
        self.other_technician = TechnicianUserFactory(company=self.company)
        self.mine = AssignedWorkOrderFactory(
            asset=self.asset, company=self.company, assigned_to=self.technician
        )
        self.theirs = AssignedWorkOrderFactory(
            asset=self.asset, company=self.company, assigned_to=self.other_technician
        )
        self.client.force_login(self.technician)

    def test_sees_only_their_own_open_work_orders(self):
        content = self.client.get(self.url).content.decode()

        assert f"#{self.mine.pk}" in content
        assert f"#{self.theirs.pk}" not in content

    def test_links_straight_to_the_execution_screen(self):
        content = self.client.get(self.url).content.decode()

        assert reverse("workorder_execute", args=[self.mine.pk]) in content
        assert "Ejecutar" in content

    def test_can_execute_from_the_scan_in_one_tap(self):
        """Criterio de salida: land on the machine, reach the execution
        screen of your own work order without typing anything."""
        response = self.client.get(
            reverse("workorder_execute", args=[self.mine.pk]), follow=True
        )

        assert response.status_code == 200
        assert "Checklist" in response.content.decode()

    def test_does_not_see_the_supervisor_panels(self):
        MaintenancePlanFactory(asset=self.asset, company=self.company)

        content = self.client.get(self.url).content.decode()

        assert "Plan de mantenimiento" not in content
        assert "Historial reciente" not in content

    def test_closed_work_orders_are_not_pending_work(self):
        self.mine.status = WorkOrder.Status.TERMINADA
        self.mine.save()

        content = self.client.get(self.url).content.decode()

        assert "No tienes órdenes pendientes en este equipo." in content


class ScanManagerTests(ScanBaseTests):
    """The supervisor's read: state, plan, what is open, what was done."""

    def setUp(self):
        super().setUp()
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.open_wo = AssignedWorkOrderFactory(
            asset=self.asset,
            company=self.company,
            assigned_to=self.technician,
            due_date=timezone.localdate() - timedelta(days=3),
        )
        self.done_wo = WorkOrderFactory(
            asset=self.asset,
            company=self.company,
            status=WorkOrder.Status.VERIFICADA,
            finished_at=timezone.now() - timedelta(days=10),
        )
        self.plan = MaintenancePlanFactory(
            asset=self.asset, company=self.company, name="Preventivo mensual línea 2"
        )
        self.client.force_login(self.supervisor)

    def test_sees_every_open_work_order_not_only_their_own(self):
        content = self.client.get(self.url).content.decode()

        assert f"#{self.open_wo.pk}" in content
        assert self.technician.username in content

    def test_sees_the_active_plan(self):
        content = self.client.get(self.url).content.decode()

        assert "Preventivo mensual línea 2" in content

    def test_sees_recent_history(self):
        content = self.client.get(self.url).content.decode()

        assert "Historial reciente" in content
        assert f"#{self.done_wo.pk}" in content

    def test_overdue_work_orders_raise_an_alert(self):
        content = self.client.get(self.url).content.decode()

        assert "1 OT vencida" in content

    def test_admin_sees_the_same_screen_as_the_supervisor(self):
        self.client.force_login(AdminUserFactory(company=self.company))

        content = self.client.get(self.url).content.decode()

        assert "Órdenes abiertas" in content
        assert "Plan de mantenimiento" in content


class ScanStaffTests(ScanBaseTests):
    """The office role reads the record. It does not act on it."""

    def setUp(self):
        super().setUp()
        self.staff = StaffUserFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.open_wo = AssignedWorkOrderFactory(
            asset=self.asset, company=self.company, assigned_to=self.technician
        )
        self.done_wo = WorkOrderFactory(
            asset=self.asset, company=self.company, status=WorkOrder.Status.VERIFICADA
        )
        self.client.force_login(self.staff)

    def test_sees_the_record_and_the_history(self):
        content = self.client.get(self.url).content.decode()

        assert "Ficha" in content
        assert "Historial reciente" in content
        assert f"#{self.done_wo.pk}" in content

    def test_gets_no_action_buttons(self):
        content = self.client.get(self.url).content.decode()

        assert "Ejecutar" not in content
        assert reverse("workorder_execute", args=[self.open_wo.pk]) not in content
        assert "Reportar falla" not in content


class ScanOtherCompanyTests(ScanBaseTests):
    """Brief item 4, decided: an authenticated outsider gets the plate.

    The assertion that matters is not "they see little" but "they see exactly
    what an anonymous visitor sees" — identical responses are what stop a
    login from being used to find out whose machine a UUID belongs to.
    """

    def setUp(self):
        super().setUp()
        self.other_company = CompanyFactory(name="Otra Empresa")
        AssignedWorkOrderFactory(asset=self.asset, company=self.company)

    def _plate_for(self, user):
        self.client.force_login(user)
        return self.client.get(self.url).content.decode()

    def test_other_company_admin_gets_the_plate(self):
        content = self._plate_for(AdminUserFactory(company=self.other_company))

        assert "FLOW-07" in content
        assert self.company.name not in content
        assert self.asset.site.name not in content
        assert "Órdenes abiertas" not in content
        assert f"/equipos/{self.asset.pk}/" not in content

    def test_other_company_technician_gets_the_plate(self):
        content = self._plate_for(TechnicianUserFactory(company=self.other_company))

        assert "Tus OTs en este equipo" not in content
        assert "FLOW-07" in content

    def test_platform_admin_gets_the_plate_too(self):
        """No company, no tenant context — so no operational read. The
        platform admin uses the ordinary equipment screens, where the
        cross-tenant bypass is explicit instead of accidental."""
        content = self._plate_for(PlatformAdminUserFactory())

        assert "FLOW-07" in content
        assert "Órdenes abiertas" not in content

    def test_the_outsider_page_is_the_anonymous_page(self):
        outsider = self._plate_for(AdminUserFactory(company=self.other_company))
        self.client.logout()
        anonymous = self.client.get(self.url).content.decode()

        # The nav differs (one has "Salir", the other "Iniciar sesión"); what
        # must match is everything the page says about the machine.
        assert self._machine_block(outsider) == self._machine_block(anonymous)

    @staticmethod
    def _machine_block(content: str) -> str:
        start = content.index('<div class="vt-plate">')
        return content[start : content.index("</main>")]
