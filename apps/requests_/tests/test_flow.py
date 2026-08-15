"""The front door, end to end: report → decide → work order.

Acceptance criteria 1 and 2 of the brief live here, plus the one thing that
must NEVER happen: a request producing two work orders.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.accounts.tests.factories import (
    CompanyFactory,
    StaffUserFactory,
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


class ReportingTests(TestCase):
    """Anybody in the company may report — including the office role, which
    may not open a work order at all."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.staff = StaffUserFactory(company=self.company)
        self.client.force_login(self.staff)
        self.url = reverse("maintenancerequest_create", args=[self.asset.pk])

    def test_staff_reports_a_failure_with_a_photo(self):
        upload = SimpleUploadedFile("falla.jpg", real_jpeg_bytes(), content_type="image/jpeg")

        response = self.client.post(
            self.url, {"description": "La banda se detiene sola.", "photo": upload}
        )

        request_obj = MaintenanceRequest.objects.unscoped().get()
        assert response.status_code == 302
        assert request_obj.reported_by_id == self.staff.pk
        assert request_obj.company_id == self.company.pk
        assert request_obj.status == MaintenanceRequest.Status.NUEVA
        # Server-generated name: the phone's filename never reaches the path.
        assert "falla.jpg" not in request_obj.photo.name
        assert request_obj.photo.name.startswith("requests/photos/")
        self.addCleanup(request_obj.photo.delete, save=False)

    def test_bytes_that_are_not_an_image_are_rejected_in_spanish(self):
        upload = SimpleUploadedFile("falsa.jpg", b"no soy una imagen", content_type="image/jpeg")

        response = self.client.post(self.url, {"description": "Algo suena mal.", "photo": upload})

        assert MaintenanceRequest.objects.unscoped().count() == 0
        assert "no es una imagen válida" in response.content.decode()

    def test_a_report_without_a_description_is_refused(self):
        response = self.client.post(self.url, {"description": ""})

        assert MaintenanceRequest.objects.unscoped().count() == 0
        assert response.status_code == 200

    def test_the_photo_is_served_through_the_gated_view(self):
        upload = SimpleUploadedFile("falla.jpg", real_jpeg_bytes(), content_type="image/jpeg")
        self.client.post(self.url, {"description": "Se detiene.", "photo": upload})
        request_obj = MaintenanceRequest.objects.unscoped().get()
        self.addCleanup(request_obj.photo.delete, save=False)

        response = self.client.get(
            reverse("maintenancerequest_photo", args=[request_obj.pk])
        )

        assert response.status_code == 200
        assert response["Content-Type"] == "image/jpeg"
        # FileResponse holds the handle open, and Windows will not delete a
        # file that is still open — so the cleanup above would fail, loudly and
        # for a reason that has nothing to do with what this test checks.
        response.close()

    def test_an_anonymous_visitor_gets_the_login_page(self):
        self.client.logout()

        response = self.client.get(self.url)

        assert response.status_code == 302
        assert reverse("login") in response.url


class ConversionTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.staff = StaffUserFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.request_obj = MaintenanceRequestFactory(
            asset=self.asset, reported_by=self.staff, description="La banda se detiene sola."
        )
        self.url = reverse("maintenancerequest_convert", args=[self.request_obj.pk])

    def test_a_supervisor_converts_it_into_a_linked_corrective_work_order(self):
        self.client.force_login(self.supervisor)

        response = self.client.post(self.url, {"priority": WorkOrder.Priority.ALTA})

        work_order = WorkOrder.objects.unscoped().get()
        self.request_obj.refresh_from_db()
        assert response.status_code == 302
        assert response.url == reverse("workorder_detail", args=[work_order.pk])
        assert work_order.type == WorkOrder.Type.CORRECTIVO
        assert work_order.origin == WorkOrder.Origin.SOLICITUD
        assert work_order.source_request_id == self.request_obj.pk
        assert work_order.asset_id == self.asset.pk
        assert work_order.priority == WorkOrder.Priority.ALTA
        # The description travels with the work order: a copy, not a pointer.
        assert work_order.failure_description == "La banda se detiene sola."
        assert self.request_obj.status == MaintenanceRequest.Status.CONVERTIDA
        assert self.request_obj.reviewed_by_id == self.supervisor.pk
        assert self.request_obj.reviewed_at is not None

    def test_a_double_click_never_creates_a_second_work_order(self):
        """The one thing that must never happen (brief: «jamás dos OTs»)."""
        self.client.force_login(self.supervisor)

        first = self.client.post(self.url, {"priority": WorkOrder.Priority.ALTA})
        second = self.client.post(self.url, {"priority": WorkOrder.Priority.CRITICA})

        assert WorkOrder.objects.unscoped().count() == 1
        # Both clicks land on the same work order, and the second is not an
        # error page: a double tap on a phone is not a mistake.
        assert first.url == second.url

    def test_the_database_itself_refuses_a_second_work_order_for_one_request(self):
        """Not «the service checks»: `UNIQUE(source_request_id)` checks.

        This is the structural half of the guarantee — the one that still holds
        for a call site nobody has written yet, exactly like
        `UNIQUE(plan, due_date)` in the scheduler.
        """
        from django.db import IntegrityError, transaction

        services.convert(self.request_obj, user=self.supervisor)

        with transaction.atomic(), self.assertRaises(IntegrityError):
            WorkOrder.objects.create(
                company_id=self.company.pk,
                asset_id=self.asset.pk,
                source_request=self.request_obj,
                type=WorkOrder.Type.CORRECTIVO,
                origin=WorkOrder.Origin.SOLICITUD,
            )

    def test_a_technician_cannot_convert(self):
        self.client.force_login(TechnicianUserFactory(company=self.company))

        response = self.client.post(self.url, {"priority": WorkOrder.Priority.ALTA})

        assert response.status_code == 403
        assert WorkOrder.objects.unscoped().count() == 0

    def test_a_rejected_request_cannot_be_converted(self):
        services.reject(self.request_obj, user=self.supervisor, note="Es ruido normal.")
        self.client.force_login(self.supervisor)

        response = self.client.post(self.url, {"priority": WorkOrder.Priority.ALTA}, follow=True)

        assert WorkOrder.objects.unscoped().count() == 0
        assert "ya fue rechazada" in response.content.decode()


class RejectionTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.staff = StaffUserFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.request_obj = MaintenanceRequestFactory(
            asset=self.asset, reported_by=self.staff
        )
        self.url = reverse("maintenancerequest_reject", args=[self.request_obj.pk])

    def test_rejecting_without_a_note_is_refused(self):
        self.client.force_login(self.supervisor)

        response = self.client.post(self.url, {"note": ""})

        self.request_obj.refresh_from_db()
        assert response.status_code == 200
        assert self.request_obj.status == MaintenanceRequest.Status.NUEVA

    def test_the_reporter_reads_the_reason(self):
        self.client.force_login(self.supervisor)
        self.client.post(self.url, {"note": "Ese ruido es normal en esta máquina."})

        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("maintenancerequest_detail", args=[self.request_obj.pk])
        )

        self.request_obj.refresh_from_db()
        assert self.request_obj.status == MaintenanceRequest.Status.RECHAZADA
        assert self.request_obj.reviewed_by_id == self.supervisor.pk
        assert "Ese ruido es normal en esta máquina." in response.content.decode()


class VisibilityTests(TestCase):
    """The reporter sees theirs. The supervisor sees the queue. Nobody else."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.reporter = TechnicianUserFactory(company=self.company)
        self.other_technician = TechnicianUserFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.request_obj = MaintenanceRequestFactory(
            asset=self.asset, reported_by=self.reporter
        )

    def test_the_reporter_sees_their_own_request_in_the_list(self):
        self.client.force_login(self.reporter)

        response = self.client.get(reverse("maintenancerequest_list"))

        assert f"#{self.request_obj.pk}" in response.content.decode()

    def test_another_technician_does_not_see_it(self):
        self.client.force_login(self.other_technician)

        listing = self.client.get(reverse("maintenancerequest_list"))
        detail = self.client.get(
            reverse("maintenancerequest_detail", args=[self.request_obj.pk])
        )

        assert f"#{self.request_obj.pk}" not in listing.content.decode()
        # 404, not 403: to them, a colleague's report does not exist.
        assert detail.status_code == 404

    def test_the_supervisor_sees_the_whole_queue(self):
        self.client.force_login(self.supervisor)

        response = self.client.get(reverse("maintenancerequest_list"))

        assert f"#{self.request_obj.pk}" in response.content.decode()

    def test_a_technician_never_sees_decision_buttons(self):
        self.client.force_login(self.reporter)

        response = self.client.get(
            reverse("maintenancerequest_detail", args=[self.request_obj.pk])
        )

        body = response.content.decode()
        assert reverse("maintenancerequest_convert", args=[self.request_obj.pk]) not in body
        assert reverse("maintenancerequest_reject", args=[self.request_obj.pk]) not in body
