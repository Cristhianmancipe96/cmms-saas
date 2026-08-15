"""Company A cannot see, decide, or even confirm the existence of company B's
failure reports (CLAUDE.md rule 1, acceptance criterion 7).

404 everywhere rather than 403: "you may not touch this" still tells a stranger
that "this" exists, and a request id is a small integer anyone can count to.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.accounts.tests.factories import (
    CompanyFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.requests_ import services
from apps.requests_.models import MaintenanceRequest
from apps.requests_.tests.factories import MaintenanceRequestFactory
from apps.workorders.models import WorkOrder


def real_jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), color="orange").save(buffer, format="JPEG")
    return buffer.getvalue()


class CrossTenantTests(TestCase):
    def setUp(self):
        self.company_a = CompanyFactory(name="Empresa A")
        self.company_b = CompanyFactory(name="Empresa B")
        self.asset_a = AssetFactory(company=self.company_a)
        self.request_a = MaintenanceRequestFactory(
            asset=self.asset_a,
            reported_by=TechnicianUserFactory(company=self.company_a),
        )
        self.supervisor_b = SupervisorUserFactory(company=self.company_b)
        self.client.force_login(self.supervisor_b)

    def test_the_detail_of_another_companys_request_is_a_404(self):
        response = self.client.get(
            reverse("maintenancerequest_detail", args=[self.request_a.pk])
        )

        assert response.status_code == 404

    def test_converting_another_companys_request_is_a_404_and_creates_nothing(self):
        response = self.client.post(
            reverse("maintenancerequest_convert", args=[self.request_a.pk]),
            {"priority": WorkOrder.Priority.ALTA},
        )

        assert response.status_code == 404
        assert WorkOrder.objects.unscoped().count() == 0

    def test_rejecting_another_companys_request_is_a_404(self):
        response = self.client.post(
            reverse("maintenancerequest_reject", args=[self.request_a.pk]),
            {"note": "No aplica."},
        )

        self.request_a.refresh_from_db()
        assert response.status_code == 404
        assert self.request_a.status == MaintenanceRequest.Status.NUEVA

    def test_another_companys_photo_is_a_404(self):
        self.request_a.photo.save(
            "falla.jpg", SimpleUploadedFile("falla.jpg", real_jpeg_bytes()), save=True
        )
        self.addCleanup(self.request_a.photo.delete, save=False)

        response = self.client.get(
            reverse("maintenancerequest_photo", args=[self.request_a.pk])
        )

        assert response.status_code == 404

    def test_the_list_never_shows_another_companys_requests(self):
        response = self.client.get(reverse("maintenancerequest_list"))

        assert f"#{self.request_a.pk}" not in response.content.decode()

    def test_reporting_a_failure_on_another_companys_asset_is_a_404(self):
        response = self.client.post(
            reverse("maintenancerequest_create", args=[self.asset_a.pk]),
            {"description": "Intento cruzado."},
        )

        assert response.status_code == 404
        assert MaintenanceRequest.objects.unscoped().count() == 1

    def test_the_service_refuses_a_cross_tenant_decision_even_without_a_view(self):
        """The rule lives in the service, not only in the URL layer."""
        with self.assertRaises(services.NotAllowed):
            services.convert(self.request_a, user=self.supervisor_b)

        assert WorkOrder.objects.unscoped().count() == 0
