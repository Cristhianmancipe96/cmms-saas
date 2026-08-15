"""What each document actually says.

Asserted against the HTML rather than against decoded PDF bytes, and that is a
design decision, not a shortcut: `documents.py` is deliberately free of
WeasyPrint so the questions an auditor cares about — is the verifier named? did
the checklist come from the snapshot? — can be asked directly. The PDF layer
gets its own test (`test_pdf_output.py`); it only has to prove that bytes come
out, not what they say.
"""

from django.test import TestCase
from django.utils import timezone

from apps.accounts.tests.factories import (
    CompanyFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.models import Asset
from apps.assets.tests.factories import AssetDocumentFactory, AssetFactory
from apps.checklists.models import ChecklistTemplateItem
from apps.checklists.tests.factories import create_flowpac_inspeccion_semanal
from apps.maintenance.tests.factories import MaintenancePlanFactory
from apps.reports import documents
from apps.reports.tests.factories import executed_work_order
from apps.workorders import services
from apps.workorders.models import WorkOrder
from apps.workorders.tests.factories import WorkOrderFactory


class AssetRecordTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory(name="Alimentos del Valle S.A.S.", nit="900123456-7")
        self.asset = AssetFactory(
            company=self.company,
            code="FLOW-07",
            name="Empacadora Flowpac 7",
            brand="Flowpac",
            serial_number="SN-000777",
        )

    def _html(self) -> str:
        return documents.build_asset_record(self.asset).html

    def test_it_names_the_machine_and_the_company(self):
        html = self._html()

        assert "FLOW-07" in html
        assert "Empacadora Flowpac 7" in html
        assert "Alimentos del Valle S.A.S." in html
        assert "900123456-7" in html
        assert self.asset.site.name in html

    def test_it_lists_the_specs_in_the_order_they_were_stored(self):
        html = self._html()

        positions = [html.index(pair["key"]) for pair in self.asset.specs]
        assert positions == sorted(positions)

    def test_it_carries_at_least_one_intervention_row(self):
        work_order = executed_work_order(company=self.company, asset=self.asset)
        html = self._html()

        assert f"#{work_order.pk}" in html
        assert work_order.completed_by.get_username() in html
        assert work_order.verified_by.get_username() in html

    def test_work_orders_still_in_progress_are_not_history(self):
        open_wo = WorkOrderFactory(asset=self.asset, status=WorkOrder.Status.EN_PROGRESO)
        html = self._html()

        assert f"#{open_wo.pk}" not in html
        assert "Todavía no se ha registrado ninguna intervención" in html

    def test_it_lists_active_plans_and_documents(self):
        plan = MaintenancePlanFactory(
            asset=self.asset, company=self.company, name="Lubricación mensual"
        )
        MaintenancePlanFactory(
            asset=self.asset, company=self.company, name="Plan archivado", is_active=False
        )
        document = AssetDocumentFactory(asset=self.asset, name="Manual del fabricante")
        html = self._html()

        assert plan.name in html
        assert "Plan archivado" not in html
        assert document.name in html

    def test_another_company_never_reaches_this_document(self):
        """Same code, same asset name, different tenant: nothing crosses."""
        other = CompanyFactory(name="Competencia S.A.S.")
        other_asset = AssetFactory(company=other, code="FLOW-07", name="Empacadora ajena")
        executed_work_order(company=other, asset=other_asset)
        html = self._html()

        assert "Competencia S.A.S." not in html
        assert "Empacadora ajena" not in html

    def test_the_photo_is_the_only_upload_the_renderer_may_reach(self):
        document = documents.build_asset_record(self.asset)
        assert document.media_names == ()

        self.asset.main_photo = "assets/photos/deadbeef.jpg"
        self.asset.save(update_fields=["main_photo"])
        document = documents.build_asset_record(self.asset)

        assert document.media_names == ("assets/photos/deadbeef.jpg",)
        assert "vectron:media/assets/photos/deadbeef.jpg" in document.html

    def test_user_text_is_escaped(self):
        self.asset.name = '<script>alert("x")</script>'
        self.asset.baja_reason = "<b>roto</b>"
        self.asset.status = Asset.Status.DADO_DE_BAJA
        self.asset.save(update_fields=["name", "baja_reason", "status"])
        html = self._html()

        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<b>roto</b>" not in html

    def test_the_file_name_folds_to_ascii(self):
        """It ends up in a latin-1 header; a stray character there is a 500."""
        self.asset.code = "FLOW/07 Ñ—日本"
        self.asset.save(update_fields=["code"])

        filename = documents.build_asset_record(self.asset).filename

        assert filename == "hoja-de-vida-FLOW-07-N.pdf"
        filename.encode("latin-1")


class WorkOrderReportTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory(name="Alimentos del Valle S.A.S.")
        self.technician = TechnicianUserFactory(
            company=self.company, first_name="Ana", last_name="Ríos"
        )
        self.supervisor = SupervisorUserFactory(
            company=self.company, first_name="Beto", last_name="Cano"
        )
        self.work_order = executed_work_order(
            company=self.company, technician=self.technician, supervisor=self.supervisor
        )

    def _html(self, work_order=None) -> str:
        return documents.build_work_order_report(work_order or self.work_order).html

    def test_the_evidence_block_names_both_people_with_their_timestamps(self):
        html = self._html()

        assert "Ejecutó" in html
        assert "Verificó" in html
        assert "Ana Ríos" in html
        assert "Beto Cano" in html
        assert self.work_order.finished_at.strftime("%d/%m/%Y") in html
        assert timezone.localtime(self.work_order.verified_at).strftime("%H:%M") in html

    def test_every_checklist_item_appears_with_its_result(self):
        html = self._html()

        assert "Revisar nivel de aceite" in html
        assert "Medir presión de aire" in html
        assert ">OK<" in html
        assert ">Falla<" in html
        assert "8,2" in html or "8.2" in html
        assert "Regulador descalibrado." in html

    def test_a_pending_verification_says_so_instead_of_inventing_a_name(self):
        work_order = executed_work_order(company=self.company, verified=False)
        html = self._html(work_order)

        assert "Pendiente de verificación" in html
        assert "Sin registrar" not in html

    def test_the_report_reads_the_snapshot_not_the_live_template(self):
        """CLAUDE.md rule 4, seen from the document that proves it."""
        template = create_flowpac_inspeccion_semanal(company=self.company)
        work_order = WorkOrderFactory(
            asset=AssetFactory(company=self.company),
            status=WorkOrder.Status.TERMINADA,
            completed_by=self.technician,
            finished_at=timezone.now(),
        )
        services.snapshot_checklist(work_order, template)
        original = ChecklistTemplateItem.objects.unscoped().filter(template=template).first()

        original_text = original.text
        assert original_text in self._html(work_order)

        # Not through a view: the point is that even a template row edited
        # directly in the database cannot reach into a report already issued.
        original.text = "TEXTO REESCRITO DESPUÉS DE LA OT"
        original.save(update_fields=["text"])
        after = self._html(work_order)

        assert "TEXTO REESCRITO DESPUÉS DE LA OT" not in after
        assert original_text in after

    def test_two_consecutive_generations_carry_the_same_evidence(self):
        """Acceptance criterion 5: the report of a sealed OT is reproducible."""
        first = self._html()
        second = self._html()
        marker = "<section>\n        <h2>Evidencia</h2>"

        assert first[first.index(marker) :] == second[second.index(marker) :]

    def test_photos_are_the_only_uploads_the_renderer_may_reach(self):
        document = documents.build_work_order_report(self.work_order)

        assert document.media_names == ()
        assert "vectron:media/" not in document.html

    def test_user_text_is_escaped(self):
        work_order = executed_work_order(company=self.company, verified=False)
        work_order.work_done = "<img src=x onerror=alert(1)>"
        work_order.save(update_fields=["work_done"])
        html = documents.build_work_order_report(work_order).html

        assert "<img src=x" not in html
        assert "&lt;img src=x" in html
