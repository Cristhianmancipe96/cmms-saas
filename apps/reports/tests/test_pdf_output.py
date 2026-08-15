"""The one place that renders a real PDF and reads the text back out.

Skipped when WeasyPrint's native libraries are not installed — on Windows that
means GTK, which the owner's machine does not have. CI runs on Linux with the
system packages installed, so these never silently vanish from the pipeline:
`test_the_engine_is_available_in_ci` fails loudly if the engine disappears from
an environment that is supposed to have it.
"""

import io
import os

import pytest
from django.core.files.base import ContentFile
from django.test import TestCase
from PIL import Image
from pypdf import PdfReader

from apps.accounts.tests.factories import (
    CompanyFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.reports import documents, pdf
from apps.reports.tests.factories import executed_work_order
from apps.workorders.models import WorkOrderPhoto

requires_engine = pytest.mark.skipif(
    not pdf.engine_available(),
    reason=(
        "WeasyPrint no puede cargar sus librerías nativas en esta máquina "
        "(en Windows: falta el runtime de GTK). Estas pruebas corren en CI."
    ),
)


def text_of(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def real_jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 90), color="orange").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_the_engine_is_available_in_ci():
    """A guard against the skip above quietly turning the suite green forever."""
    if os.environ.get("CI"):
        assert pdf.engine_available(), "CI must install WeasyPrint's system libraries"


@requires_engine
class AssetRecordPdfTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory(name="Alimentos del Valle S.A.S.", nit="900123456-7")
        self.asset = AssetFactory(
            company=self.company, code="FLOW-07", name="Empacadora Flowpac 7"
        )
        self.work_order = executed_work_order(company=self.company, asset=self.asset)

    def test_it_produces_a_pdf_that_reads_back_as_the_equipment_record(self):
        content = documents.build_asset_record(self.asset).render_pdf()

        assert content.startswith(b"%PDF-")
        text = text_of(content)
        assert "FLOW-07" in text
        assert "Alimentos del Valle S.A.S." in text
        assert f"#{self.work_order.pk}" in text
        assert "Historial de intervenciones" in text

    def test_the_equipment_photo_is_embedded(self):
        self.asset.main_photo.save("foto.jpg", ContentFile(real_jpeg_bytes()), save=True)
        self.addCleanup(self.asset.main_photo.delete, save=False)

        document = documents.build_asset_record(self.asset)
        content = document.render_pdf()

        assert document.media_names == (self.asset.main_photo.name,)
        reader = PdfReader(io.BytesIO(content))
        assert list(reader.pages[0].images), "la foto del equipo no llegó al PDF"


@requires_engine
class WorkOrderReportPdfTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.technician = TechnicianUserFactory(
            company=self.company, first_name="Ana", last_name="Ríos"
        )
        self.supervisor = SupervisorUserFactory(
            company=self.company, first_name="Beto", last_name="Cano"
        )
        self.work_order = executed_work_order(
            company=self.company, technician=self.technician, supervisor=self.supervisor
        )

    def test_it_names_both_people_and_every_checklist_item(self):
        text = text_of(documents.build_work_order_report(self.work_order).render_pdf())

        assert "Ana Ríos" in text
        assert "Beto Cano" in text
        assert "Revisar nivel de aceite" in text
        assert "Medir presión de aire" in text
        assert "Falla" in text

    def test_two_generations_of_a_sealed_report_say_the_same_thing(self):
        first = text_of(documents.build_work_order_report(self.work_order).render_pdf())
        second = text_of(documents.build_work_order_report(self.work_order).render_pdf())

        evidence = "Evidencia"
        assert first[first.index(evidence) :] == second[second.index(evidence) :]

    def test_work_order_photos_travel_with_the_report(self):
        # An unsealed work order: photos are attached while the job is being
        # done, which is exactly when this one still can be.
        work_order = executed_work_order(company=self.company, verified=False)
        photo = WorkOrderPhoto(
            company_id=self.company.pk, work_order=work_order, caption="Rodamiento cambiado"
        )
        photo.image.save("evidencia.jpg", ContentFile(real_jpeg_bytes()), save=True)
        self.addCleanup(photo.image.delete, save=False)

        document = documents.build_work_order_report(work_order)
        assert document.media_names == (photo.image.name,)

        reader = PdfReader(io.BytesIO(document.render_pdf()))
        assert any(list(page.images) for page in reader.pages), (
            "el registro fotográfico no llegó al PDF"
        )
