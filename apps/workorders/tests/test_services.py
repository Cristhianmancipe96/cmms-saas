"""The state machine, tested exhaustively and without a browser.

Acceptance criterion 1 asks for *every* (state, action, role) combination:
allowed ones succeed, all others raise. `TransitionMatrixTests` builds that
product in code rather than writing a hundred hand-copied tests — a
hand-written matrix is a matrix with a hole in it, and the hole is always in
the row nobody thought about.
"""

from decimal import Decimal

import pytest
from django.test import TestCase
from django.utils import timezone

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.checklists.tests.factories import create_flowpac_inspeccion_semanal
from apps.maintenance.models import MeterReading
from apps.maintenance.tests.factories import MeterPlanFactory, MeterReadingFactory
from apps.workorders import services
from apps.workorders.models import WorkOrder, WorkOrderChecklistItem
from apps.workorders.tests.factories import WorkOrderChecklistItemFactory, WorkOrderFactory

STATUSES = [status for status, _label in WorkOrder.Status.choices]
ACTIONS = [services.ASSIGN, services.START, services.COMPLETE, services.VERIFY, services.CANCEL]

# The actor kinds the matrix distinguishes. "role" alone is not enough: start
# and complete are decided by identity (are you the assignee?), which is the
# whole point of CLAUDE.md rule 3, so the assigned technician and a different
# technician of the same company are two different rows.
ACTOR_KINDS = ["admin", "supervisor", "assignee", "other_technician", "staff"]

# The expected truth table, written out on purpose rather than derived from
# services.TRANSITIONS — a table generated from the implementation would agree
# with any bug the implementation has.
ALLOWED: set[tuple[str, str, str]] = {
    # assign: supervisors and admins, while the work has not started.
    *{("abierta", "assign", actor) for actor in ("admin", "supervisor")},
    *{("asignada", "assign", actor) for actor in ("admin", "supervisor")},
    # start / complete: the assigned person, nobody else — not even an admin.
    ("asignada", "start", "assignee"),
    ("en_progreso", "complete", "assignee"),
    # verify: a manager who is not the executor (see ExecutorNeverVerifiesTests).
    *{("terminada", "verify", actor) for actor in ("admin", "supervisor")},
    # cancel: a manager, from anything not already finished.
    *{
        (status, "cancel", actor)
        for status in ("abierta", "asignada", "en_progreso", "terminada")
        for actor in ("admin", "supervisor")
    },
}


class TransitionMatrixTests(TestCase):
    """Acceptance criterion 1: the whole product of states, actions and actors."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.assignee = TechnicianUserFactory(company=self.company)
        self.actors = {
            "admin": AdminUserFactory(company=self.company),
            "supervisor": SupervisorUserFactory(company=self.company),
            "assignee": self.assignee,
            "other_technician": TechnicianUserFactory(company=self.company),
            "staff": StaffUserFactory(company=self.company),
        }

    def _work_order(self, status: str) -> WorkOrder:
        """A work order parked in `status`, always assigned, always with the
        executor recorded — so the only thing the matrix varies is the actor."""
        work_order = WorkOrderFactory(
            asset=self.asset,
            status=WorkOrder.Status.ABIERTA,
            assigned_to=self.assignee,
        )
        WorkOrder.objects.unscoped().filter(pk=work_order.pk).update(
            status=status,
            completed_by=self.assignee,
            finished_at=timezone.now(),
        )
        return WorkOrder.objects.unscoped().get(pk=work_order.pk)

    def _payload(self, action: str) -> dict:
        return {
            services.ASSIGN: {"assignee": self.assignee},
            services.CANCEL: {"reason": "El equipo salió de servicio."},
        }.get(action, {})

    def test_every_state_action_actor_combination_behaves_as_the_table_says(self):
        for status in STATUSES:
            for action in ACTIONS:
                for actor_kind in ACTOR_KINDS:
                    expected_allowed = (status, action, actor_kind) in ALLOWED
                    with self.subTest(status=status, action=action, actor=actor_kind):
                        work_order = self._work_order(status)
                        user = self.actors[actor_kind]
                        if expected_allowed:
                            result = services.transition(
                                work_order, action, user, **self._payload(action)
                            )
                            assert result.status == services.TRANSITIONS[action].to_status
                        else:
                            with pytest.raises(services.WorkOrderError):
                                services.transition(
                                    work_order, action, user, **self._payload(action)
                                )
                            assert (
                                WorkOrder.objects.unscoped().get(pk=work_order.pk).status
                                == status
                            )

    def test_verify_on_a_work_order_that_is_not_terminada_always_raises(self):
        """Called out separately in criterion 1 because it is the combination
        an over-eager supervisor actually attempts."""
        for status in ("abierta", "asignada", "en_progreso", "verificada", "cancelada"):
            with self.subTest(status=status):
                work_order = self._work_order(status)

                with pytest.raises(services.InvalidTransition):
                    services.transition(
                        work_order, services.VERIFY, self.actors["supervisor"]
                    )

    def test_an_unknown_action_raises_instead_of_doing_nothing(self):
        work_order = self._work_order("abierta")

        with pytest.raises(services.InvalidTransition):
            services.transition(work_order, "aprobar_todo", self.actors["admin"])

    def test_the_refusal_messages_are_in_spanish(self):
        work_order = self._work_order("abierta")

        with pytest.raises(services.InvalidTransition) as excinfo:
            services.transition(work_order, services.VERIFY, self.actors["admin"])
        assert "No se puede verificar una OT abierta." in str(excinfo.value)

        with pytest.raises(services.NotAllowed) as excinfo:
            services.transition(
                work_order, services.ASSIGN, self.actors["staff"], assignee=self.assignee
            )
        assert "supervisor" in str(excinfo.value)


class ExecutorNeverVerifiesTests(TestCase):
    """Acceptance criterion 2 — the rule the whole product rests on."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)

    def _terminada_by(self, executor) -> WorkOrder:
        work_order = WorkOrderFactory(asset=self.asset, assigned_to=executor)
        WorkOrder.objects.unscoped().filter(pk=work_order.pk).update(
            status=WorkOrder.Status.TERMINADA,
            completed_by=executor,
            finished_at=timezone.now(),
        )
        return WorkOrder.objects.unscoped().get(pk=work_order.pk)

    def test_a_supervisor_cannot_verify_the_work_order_they_executed(self):
        supervisor = SupervisorUserFactory(company=self.company)
        work_order = self._terminada_by(supervisor)

        with pytest.raises(services.NotAllowed) as excinfo:
            services.transition(work_order, services.VERIFY, supervisor)

        assert "Quien ejecuta una OT no puede verificarla" in str(excinfo.value)
        assert (
            WorkOrder.objects.unscoped().get(pk=work_order.pk).status
            == WorkOrder.Status.TERMINADA
        )

    def test_an_admin_cannot_verify_the_work_order_they_executed(self):
        admin = AdminUserFactory(company=self.company)
        work_order = self._terminada_by(admin)

        with pytest.raises(services.NotAllowed):
            services.transition(work_order, services.VERIFY, admin)

    def test_a_different_supervisor_can_verify_it(self):
        executor = SupervisorUserFactory(company=self.company)
        other = SupervisorUserFactory(company=self.company)
        work_order = self._terminada_by(executor)

        verified = services.transition(work_order, services.VERIFY, other)

        assert verified.status == WorkOrder.Status.VERIFICADA
        assert verified.verified_by_id == other.pk
        assert verified.verified_at is not None

    def test_a_work_order_with_no_recorded_executor_cannot_be_verified(self):
        """Unreachable through `complete`, which always stamps the executor.
        Refusing is the safe direction: with no executor on file there is no
        way to prove separation of duties held."""
        work_order = WorkOrderFactory(asset=self.asset, status=WorkOrder.Status.TERMINADA)
        supervisor = SupervisorUserFactory(company=self.company)

        with pytest.raises(services.NotAllowed) as excinfo:
            services.transition(work_order, services.VERIFY, supervisor)

        assert "no registra quién la ejecutó" in str(excinfo.value)

    def test_verifying_records_the_executor_from_completion_not_the_assignee_field(self):
        """The whole flow, honestly: assign -> start -> complete -> verify."""
        technician = TechnicianUserFactory(company=self.company)
        supervisor = SupervisorUserFactory(company=self.company)
        work_order = WorkOrderFactory(asset=self.asset, status=WorkOrder.Status.ABIERTA)

        services.transition(work_order, services.ASSIGN, supervisor, assignee=technician)
        services.transition(work_order, services.START, technician)
        completed = services.transition(work_order, services.COMPLETE, technician)

        assert completed.completed_by_id == technician.pk
        verified = services.transition(work_order, services.VERIFY, supervisor)
        assert verified.verified_by_id == supervisor.pk


class CompletionRequiresTheChecklistTests(TestCase):
    """Acceptance criterion 5, first half."""

    def setUp(self):
        self.company = CompanyFactory()
        self.technician = TechnicianUserFactory(company=self.company)
        self.work_order = WorkOrderFactory(
            asset=AssetFactory(company=self.company),
            status=WorkOrder.Status.EN_PROGRESO,
            assigned_to=self.technician,
        )

    def test_an_unanswered_required_item_blocks_completion(self):
        WorkOrderChecklistItemFactory(work_order=self.work_order, order=1, required=True)

        with pytest.raises(services.IncompleteChecklist) as excinfo:
            services.transition(self.work_order, services.COMPLETE, self.technician)

        assert "obligatorio" in str(excinfo.value)
        assert (
            WorkOrder.objects.unscoped().get(pk=self.work_order.pk).status
            == WorkOrder.Status.EN_PROGRESO
        )

    def test_an_unanswered_optional_item_does_not_block_completion(self):
        WorkOrderChecklistItemFactory(work_order=self.work_order, order=1, required=False)

        completed = services.transition(self.work_order, services.COMPLETE, self.technician)

        assert completed.status == WorkOrder.Status.TERMINADA

    def test_answering_every_required_item_unblocks_completion(self):
        item = WorkOrderChecklistItemFactory(
            work_order=self.work_order, order=1, required=True
        )
        services.record_item_result(
            self.work_order, item, user=self.technician, result="ok"
        )

        completed = services.transition(self.work_order, services.COMPLETE, self.technician)

        assert completed.status == WorkOrder.Status.TERMINADA
        assert completed.finished_at is not None

    def test_the_pending_check_reads_the_database_not_an_empty_scoped_manager(self):
        """The silent-no-op trap: `work_order.checklist_items` goes through a
        CompanyScopedManager, which returns nothing with no tenant contextvar
        set — exactly this situation. If the service used it, an empty
        checklist would wave every work order through as complete."""
        WorkOrderChecklistItemFactory(work_order=self.work_order, order=1, required=True)

        from apps.core.tenancy import current_company_id

        assert current_company_id.get() is None
        assert len(services.pending_required_items(self.work_order)) == 1

    def test_closing_numbers_are_stored_on_completion(self):
        completed = services.transition(
            self.work_order,
            services.COMPLETE,
            self.technician,
            work_done="Se cambió el rodamiento",
            downtime_minutes=45,
            labor_cost_cop=120_000,
            parts_cost_cop=80_000,
        )

        assert completed.work_done == "Se cambió el rodamiento"
        assert completed.downtime_minutes == 45
        assert completed.total_cost_cop == 200_000


class NumericResultTests(TestCase):
    """Acceptance criterion 5, second half: out of range IS a failure, and
    that verdict is arithmetic, never something the form gets to assert."""

    def setUp(self):
        self.company = CompanyFactory()
        self.technician = TechnicianUserFactory(company=self.company)
        self.work_order = WorkOrderFactory(
            asset=AssetFactory(company=self.company),
            status=WorkOrder.Status.EN_PROGRESO,
            assigned_to=self.technician,
        )
        self.item = WorkOrderChecklistItemFactory(
            work_order=self.work_order,
            order=1,
            item_type=WorkOrderChecklistItem.ItemType.NUMERIC,
            unit="bar",
            min_value=Decimal("5.00"),
            max_value=Decimal("7.00"),
        )

    def _record(self, value, **kwargs):
        return services.record_item_result(
            self.work_order,
            self.item,
            user=self.technician,
            numeric_value=Decimal(value) if value is not None else None,
            **kwargs,
        )

    def test_a_value_above_the_maximum_stores_falla(self):
        assert self._record("9.50").result == WorkOrderChecklistItem.Result.FALLA

    def test_a_value_below_the_minimum_stores_falla(self):
        assert self._record("1.00").result == WorkOrderChecklistItem.Result.FALLA

    def test_a_value_inside_the_range_stores_ok(self):
        assert self._record("6.00").result == WorkOrderChecklistItem.Result.OK

    def test_the_bounds_themselves_are_inside_the_range(self):
        assert self._record("5.00").result == WorkOrderChecklistItem.Result.OK
        assert self._record("7.00").result == WorkOrderChecklistItem.Result.OK

    def test_the_measured_value_is_stored_alongside_the_verdict(self):
        item = self._record("9.50")

        assert item.numeric_value == Decimal("9.50")

    def test_a_result_sent_by_the_client_cannot_override_the_arithmetic(self):
        """A crafted POST claiming "ok" for an out-of-range reading must not
        be believed: the failure is in the number, not in the button."""
        item = self._record("9.50", result=WorkOrderChecklistItem.Result.OK)

        assert item.result == WorkOrderChecklistItem.Result.FALLA

    def test_marking_it_na_clears_the_value(self):
        self._record("6.00")

        item = self._record(None, result=WorkOrderChecklistItem.Result.NA)

        assert item.result == WorkOrderChecklistItem.Result.NA
        assert item.numeric_value is None

    def test_saving_a_numeric_item_without_a_value_is_refused_in_spanish(self):
        with pytest.raises(services.WorkOrderError) as excinfo:
            self._record(None)

        assert "valor medido" in str(excinfo.value)


class RecordItemResultGuardTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.technician = TechnicianUserFactory(company=self.company)
        self.work_order = WorkOrderFactory(
            asset=AssetFactory(company=self.company),
            status=WorkOrder.Status.EN_PROGRESO,
            assigned_to=self.technician,
        )
        self.item = WorkOrderChecklistItemFactory(work_order=self.work_order, order=1)

    def test_another_technician_cannot_answer_the_checklist(self):
        intruder = TechnicianUserFactory(company=self.company)

        with pytest.raises(services.NotAllowed):
            services.record_item_result(
                self.work_order, self.item, user=intruder, result="ok"
            )

    def test_a_supervisor_cannot_answer_someone_elses_checklist(self):
        """Supervising is not executing. A supervisor who wants to fill this in
        assigns it to themselves first — and thereby gives up verifying it."""
        supervisor = SupervisorUserFactory(company=self.company)

        with pytest.raises(services.NotAllowed):
            services.record_item_result(
                self.work_order, self.item, user=supervisor, result="ok"
            )

    def test_answers_are_refused_before_the_work_order_is_started(self):
        WorkOrder.objects.unscoped().filter(pk=self.work_order.pk).update(
            status=WorkOrder.Status.ASIGNADA
        )
        work_order = WorkOrder.objects.unscoped().get(pk=self.work_order.pk)

        with pytest.raises(services.NotAllowed):
            services.record_item_result(
                work_order, self.item, user=self.technician, result="ok"
            )

    def test_an_item_from_another_work_order_is_refused(self):
        other = WorkOrderFactory(
            asset=AssetFactory(company=self.company),
            status=WorkOrder.Status.EN_PROGRESO,
            assigned_to=self.technician,
        )
        foreign_item = WorkOrderChecklistItemFactory(work_order=other, order=1)

        with pytest.raises(services.NotAllowed):
            services.record_item_result(
                self.work_order, foreign_item, user=self.technician, result="ok"
            )

    def test_a_nonsense_result_is_refused(self):
        with pytest.raises(services.WorkOrderError):
            services.record_item_result(
                self.work_order, self.item, user=self.technician, result="excelente"
            )

    def test_a_note_travels_with_the_answer(self):
        item = services.record_item_result(
            self.work_order,
            self.item,
            user=self.technician,
            result="falla",
            note="  Sale aceite por el retén  ",
        )

        assert item.note == "Sale aceite por el retén"


class CancelTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.work_order = WorkOrderFactory(asset=AssetFactory(company=self.company))

    def test_cancelling_without_a_reason_is_refused_in_spanish(self):
        with pytest.raises(services.WorkOrderError) as excinfo:
            services.transition(self.work_order, services.CANCEL, self.supervisor, reason="  ")

        assert "motivo" in str(excinfo.value)
        assert (
            WorkOrder.objects.unscoped().get(pk=self.work_order.pk).status
            == WorkOrder.Status.ABIERTA
        )

    def test_the_reason_is_stored(self):
        cancelled = services.transition(
            self.work_order, services.CANCEL, self.supervisor, reason="Equipo dado de baja"
        )

        assert cancelled.status == WorkOrder.Status.CANCELADA
        assert cancelled.cancel_reason == "Equipo dado de baja"

    def test_a_verified_work_order_cannot_be_cancelled(self):
        WorkOrder.objects.unscoped().filter(pk=self.work_order.pk).update(
            status=WorkOrder.Status.VERIFICADA
        )
        work_order = WorkOrder.objects.unscoped().get(pk=self.work_order.pk)

        with pytest.raises(services.InvalidTransition):
            services.transition(
                work_order, services.CANCEL, self.supervisor, reason="Ya no sirve"
            )


class MeterIntegrationTests(TestCase):
    """Build item 7: closing a work order on a metered machine records the hours."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.technician = TechnicianUserFactory(company=self.company)
        self.work_order = WorkOrderFactory(
            asset=self.asset,
            status=WorkOrder.Status.EN_PROGRESO,
            assigned_to=self.technician,
        )

    def test_an_asset_with_an_active_meter_plan_is_tracked(self):
        MeterPlanFactory(company=self.company, asset=self.asset)

        assert services.asset_tracks_meter(self.asset.pk) is True

    def test_an_asset_with_readings_but_no_meter_plan_is_tracked(self):
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("100"))

        assert services.asset_tracks_meter(self.asset.pk) is True

    def test_an_asset_with_neither_is_not_tracked(self):
        assert services.asset_tracks_meter(self.asset.pk) is False

    def test_completing_with_a_reading_records_it_as_source_work_order(self):
        MeterPlanFactory(company=self.company, asset=self.asset)

        services.transition(
            self.work_order,
            services.COMPLETE,
            self.technician,
            meter_reading_hours=Decimal("1250.50"),
        )

        reading = MeterReading.objects.unscoped().get(asset=self.asset)
        assert reading.reading_hours == Decimal("1250.50")
        assert reading.source == MeterReading.Source.WORK_ORDER
        assert reading.recorded_by_id == self.technician.pk
        assert reading.company_id == self.company.pk

    def test_completing_without_a_reading_records_nothing(self):
        services.transition(self.work_order, services.COMPLETE, self.technician)

        assert MeterReading.objects.unscoped().filter(asset=self.asset).count() == 0

    def test_a_reading_lower_than_the_last_one_is_refused_at_completion(self):
        """The monotonic rule is the meter's, not the panel's: closing a work
        order must not be a side door around it."""
        MeterReadingFactory(asset=self.asset, reading_hours=Decimal("5000.00"))

        # A WorkOrderError, not a bare ValidationError: this module keeps one
        # refusal type so the views can render every refusal the same way
        # instead of letting one escape as a 500.
        with pytest.raises(services.WorkOrderError) as excinfo:
            services.transition(
                self.work_order,
                services.COMPLETE,
                self.technician,
                meter_reading_hours=Decimal("100.00"),
            )

        assert "no puede ser menor" in str(excinfo.value)
        assert MeterReading.objects.unscoped().filter(asset=self.asset).count() == 1
        assert (
            WorkOrder.objects.unscoped().get(pk=self.work_order.pk).status
            == WorkOrder.Status.EN_PROGRESO
        )


class AvailableActionsTests(TestCase):
    """The screens ask the matrix instead of re-deriving it, so a button that
    renders is a button that works."""

    def setUp(self):
        self.company = CompanyFactory()
        self.technician = TechnicianUserFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)

    def test_an_open_work_order_offers_assign_and_cancel_to_a_supervisor(self):
        work_order = WorkOrderFactory(asset=AssetFactory(company=self.company))

        actions = services.available_actions(work_order, self.supervisor)

        assert set(actions) == {services.ASSIGN, services.CANCEL}

    def test_an_assigned_work_order_offers_start_to_its_assignee_only(self):
        work_order = WorkOrderFactory(
            asset=AssetFactory(company=self.company),
            status=WorkOrder.Status.ASIGNADA,
            assigned_to=self.technician,
        )

        assert services.available_actions(work_order, self.technician) == [services.START]
        other = TechnicianUserFactory(company=self.company)
        assert services.available_actions(work_order, other) == []

    def test_a_verified_work_order_offers_nothing_to_anyone(self):
        work_order = WorkOrderFactory(
            asset=AssetFactory(company=self.company), status=WorkOrder.Status.VERIFICADA
        )

        assert services.available_actions(work_order, self.supervisor) == []
        assert services.available_actions(work_order, self.technician) == []

    def test_another_companys_user_is_offered_nothing(self):
        work_order = WorkOrderFactory(asset=AssetFactory(company=self.company))
        outsider = AdminUserFactory(company=CompanyFactory())

        assert services.available_actions(work_order, outsider) == []


class SnapshotFromTheSchedulerTests(TestCase):
    """The scheduler hook: a plan-generated work order is born with its
    checklist already frozen (build item 2)."""

    def test_generated_work_orders_carry_a_snapshot_of_the_resolved_version(self):
        from apps.maintenance import services as maintenance_services
        from apps.maintenance.tests.factories import MaintenancePlanFactory

        company = CompanyFactory()
        asset = AssetFactory(company=company)
        template = create_flowpac_inspeccion_semanal(company=company)
        plan = MaintenancePlanFactory(
            company=company,
            asset=asset,
            checklist_template=template,
            next_due_date=timezone.localdate(),
        )

        maintenance_services.generate_for_company(company, today=timezone.localdate())

        work_order = WorkOrder.objects.unscoped().get(plan=plan)
        assert work_order.checklist_template_id == template.pk
        assert len(list(services.checklist_items(work_order))) == 3

    def test_a_second_scheduler_run_does_not_append_a_second_snapshot(self):
        """Idempotency (CLAUDE.md rule 5) extended to the work order's children:
        the row is not duplicated, so neither is its checklist."""
        from apps.maintenance import services as maintenance_services
        from apps.maintenance.tests.factories import MaintenancePlanFactory

        company = CompanyFactory()
        asset = AssetFactory(company=company)
        template = create_flowpac_inspeccion_semanal(company=company)
        MaintenancePlanFactory(
            company=company,
            asset=asset,
            checklist_template=template,
            next_due_date=timezone.localdate(),
        )
        today = timezone.localdate()

        maintenance_services.generate_for_company(company, today=today)
        maintenance_services.generate_for_company(company, today=today)

        work_order = WorkOrder.objects.unscoped().get(asset=asset)
        assert len(list(services.checklist_items(work_order))) == 3

    def test_a_plan_without_a_template_generates_a_work_order_without_a_checklist(self):
        from apps.maintenance import services as maintenance_services
        from apps.maintenance.tests.factories import MaintenancePlanFactory

        company = CompanyFactory()
        asset = AssetFactory(company=company)
        MaintenancePlanFactory(
            company=company,
            asset=asset,
            checklist_template=None,
            next_due_date=timezone.localdate(),
        )

        maintenance_services.generate_for_company(company, today=timezone.localdate())

        work_order = WorkOrder.objects.unscoped().get(asset=asset)
        assert work_order.checklist_template_id is None
        assert list(services.checklist_items(work_order)) == []
