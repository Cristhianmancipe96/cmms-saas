"""Acceptance criterion 7, first half: every work-order URL 404s across tenants.

404, not 403, on purpose. A 403 confirms the row exists, which is an existence
oracle: an outsider could walk the primary keys and learn how many work orders
a competitor runs. The scoped manager makes "not yours" and "not there"
indistinguishable, and this module proves it for every route the brief adds.
"""

import pytest
from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    PlatformAdminUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.checklists.tests.factories import create_flowpac_inspeccion_semanal
from apps.workorders import services
from apps.workorders.models import WorkOrder, WorkOrderPhoto
from apps.workorders.tests.factories import WorkOrderFactory, WorkOrderPhotoFactory


class CrossTenantWorkOrderUrlsTests(TestCase):
    def setUp(self):
        self.mine = CompanyFactory()
        self.theirs = CompanyFactory()
        self.their_asset = AssetFactory(company=self.theirs)
        self.their_technician = TechnicianUserFactory(company=self.theirs)
        self.their_work_order = WorkOrderFactory(
            asset=self.their_asset,
            status=WorkOrder.Status.EN_PROGRESO,
            assigned_to=self.their_technician,
        )
        services.snapshot_checklist(
            self.their_work_order, create_flowpac_inspeccion_semanal(company=self.theirs)
        )
        self.their_item = services.checklist_items(self.their_work_order).first()
        self.their_photo = WorkOrderPhotoFactory(work_order=self.their_work_order)

        # An *admin* of the other company: the most privileged outsider there
        # is. If tenancy leaked anywhere, it would leak here first.
        self.client.force_login(AdminUserFactory(company=self.mine))

    def _get_urls(self) -> list[str]:
        pk = self.their_work_order.pk
        return [
            reverse("workorder_detail", args=[pk]),
            reverse("workorder_execute", args=[pk]),
            reverse("workorder_verify", args=[pk]),
            reverse("workorder_cancel", args=[pk]),
            reverse("workorder_photo_download", args=[pk, self.their_photo.pk]),
            reverse("workorder_corrective_create", args=[self.their_asset.pk]),
        ]

    def _post_urls(self) -> list[tuple[str, dict]]:
        pk = self.their_work_order.pk
        return [
            (reverse("workorder_assign", args=[pk]), {"assignee": self.their_technician.pk}),
            (reverse("workorder_start", args=[pk]), {}),
            (reverse("workorder_complete", args=[pk]), {"work_done": "intruso"}),
            (reverse("workorder_verify", args=[pk]), {}),
            (reverse("workorder_cancel", args=[pk]), {"reason": "intruso"}),
            (reverse("workorder_item_save", args=[pk, self.their_item.pk]), {"result": "ok"}),
            (reverse("workorder_photo_upload", args=[pk]), {}),
        ]

    def test_every_get_url_404s_for_another_companys_admin(self):
        for url in self._get_urls():
            with self.subTest(url=url):
                assert self.client.get(url).status_code == 404

    def test_every_post_url_404s_for_another_companys_admin(self):
        for url, payload in self._post_urls():
            with self.subTest(url=url):
                assert self.client.post(url, payload).status_code == 404

    def test_nothing_was_written_by_any_of_those_attempts(self):
        for url, payload in self._post_urls():
            self.client.post(url, payload)

        work_order = WorkOrder.objects.unscoped().get(pk=self.their_work_order.pk)
        assert work_order.status == WorkOrder.Status.EN_PROGRESO
        assert work_order.work_done == ""
        assert work_order.cancel_reason == ""
        assert services.checklist_items(work_order).first().result == ""
        assert WorkOrderPhoto.objects.unscoped().filter(work_order=work_order).count() == 1

    def test_another_companys_work_orders_never_appear_in_the_list(self):
        my_work_order = WorkOrderFactory(asset=AssetFactory(company=self.mine))

        response = self.client.get(reverse("workorder_list"))

        listed = [wo.pk for wo in response.context["work_orders"]]
        assert listed == [my_work_order.pk]

    def test_another_companys_work_orders_never_appear_in_mis_ots(self):
        """Even for a user with the same primary key story: assignment is a
        foreign key, but the queryset is scoped first."""
        technician = TechnicianUserFactory(company=self.mine)
        self.client.force_login(technician)

        response = self.client.get(reverse("workorder_mine"))

        assert response.context["total"] == 0


class CrossTenantServiceTests(TestCase):
    """The service is callable outside a request, where no middleware has set
    the tenant contextvar. Its own company check is what keeps that safe."""

    def test_transition_refuses_a_work_order_from_another_company(self):
        theirs = CompanyFactory()
        work_order = WorkOrderFactory(asset=AssetFactory(company=theirs))
        outsider = SupervisorUserFactory(company=CompanyFactory())

        with pytest.raises(services.NotAllowed) as excinfo:
            services.transition(
                work_order, services.CANCEL, outsider, reason="No es mía"
            )

        assert "no pertenece a tu empresa" in str(excinfo.value)
        assert (
            WorkOrder.objects.unscoped().get(pk=work_order.pk).status
            == WorkOrder.Status.ABIERTA
        )

    def test_a_platform_admin_is_allowed_across_tenants(self):
        """The one sanctioned exception, same as everywhere else in the app."""
        theirs = CompanyFactory()
        work_order = WorkOrderFactory(asset=AssetFactory(company=theirs))

        cancelled = services.transition(
            work_order,
            services.CANCEL,
            PlatformAdminUserFactory(),
            reason="Soporte de plataforma",
        )

        assert cancelled.status == WorkOrder.Status.CANCELADA
