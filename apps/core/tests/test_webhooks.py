"""What n8n receives, and what happens to the CMMS when n8n does not answer.

The rule under test is PLAN §7 stated as three separate promises:

1. Nothing is emitted when nobody asked for it (`N8N_WEBHOOK_URL` unset).
2. What is emitted carries the token in a header and nothing personal in the
   body — and the signature over those exact bytes verifies.
3. An endpoint that hangs costs the operator nothing: not an error, not a
   rollback, and not seconds on their screen.
"""

import hashlib
import hmac
import json
import time
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.tests.factories import (
    CompanyFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.assets.tests.factories import AssetFactory
from apps.core import webhooks
from apps.core.tests.webhook_server import RecordingWebhookServer, wait_for_delivery
from apps.maintenance import services as maintenance_services
from apps.requests_ import services as request_services
from apps.workorders import services as workorder_services
from apps.workorders.models import WorkOrder
from apps.workorders.tests.factories import AssignedWorkOrderFactory

TOKEN = "un-token-de-prueba-1234567890"


class NotConfiguredTests(TestCase):
    @override_settings(N8N_WEBHOOK_URL="", N8N_WEBHOOK_TOKEN="")
    def test_nothing_is_emitted_when_no_url_is_configured(self):
        """The normal state of every development machine and of this suite."""
        assert webhooks.is_configured() is False
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            webhooks.emit(
                webhooks.EVENT_WORK_ORDER_CREATED,
                company_id=1,
                object_type="orden_de_trabajo",
                object_id=1,
                data={"estado": "abierta"},
            )
        assert callbacks == []
        assert webhooks.send({"evento": "x"}) is None


class SignatureTests(TestCase):
    def test_the_signature_is_the_hmac_of_the_exact_bytes_sent(self):
        body = json.dumps({"evento": "ot_verificada"}).encode("utf-8")
        expected = hmac.new(TOKEN.encode("utf-8"), body, hashlib.sha256).hexdigest()

        assert webhooks.signature(body, TOKEN) == f"sha256={expected}"


class DeliveryTests(TestCase):
    """The wire, end to end, against a real socket."""

    def setUp(self):
        self.company = CompanyFactory()
        self.technician = TechnicianUserFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.asset = AssetFactory(company=self.company, code="COMP-01", name="Compresor")

    def _verified_work_order(self):
        work_order = AssignedWorkOrderFactory(
            asset=self.asset, assigned_to=self.technician, company=self.company
        )
        workorder_services.transition(work_order, workorder_services.START, self.technician)
        workorder_services.transition(work_order, workorder_services.COMPLETE, self.technician)
        return work_order

    def test_a_verified_work_order_arrives_signed_and_with_its_token(self):
        work_order = self._verified_work_order()

        with RecordingWebhookServer() as server:
            with override_settings(
                N8N_WEBHOOK_URL=server.url, N8N_WEBHOOK_TOKEN=TOKEN
            ), self.captureOnCommitCallbacks(execute=True):
                workorder_services.transition(
                    work_order, workorder_services.VERIFY, self.supervisor
                )
            wait_for_delivery()

            assert len(server.received) == 1
            entry = server.received[0]
            assert entry["headers"]["X-Vectron-Token"] == TOKEN
            # Recomputed here from the bytes the server actually read, which is
            # the only version of the body worth signing.
            expected = hmac.new(
                TOKEN.encode("utf-8"), entry["raw"], hashlib.sha256
            ).hexdigest()
            assert entry["headers"]["X-Vectron-Signature"] == f"sha256={expected}"

            payload = server.payloads()[0]
            assert payload["evento"] == webhooks.EVENT_WORK_ORDER_VERIFIED
            assert payload["empresa_id"] == self.company.pk
            assert payload["objeto"] == {"tipo": "orden_de_trabajo", "id": work_order.pk}
            assert payload["datos"]["estado"] == WorkOrder.Status.VERIFICADA

    def test_the_payload_carries_no_names_and_no_free_text(self):
        """Least privilege applies to messages too: ids and enums, never people.

        n8n queries back with its own token when it needs detail — so a leaked
        or misrouted webhook body must not be enough to learn who works here or
        what broke.
        """
        staff = StaffUserFactory(company=self.company)

        with RecordingWebhookServer() as server:
            with override_settings(
                N8N_WEBHOOK_URL=server.url, N8N_WEBHOOK_TOKEN=TOKEN
            ), self.captureOnCommitCallbacks(execute=True):
                request_services.create_request(
                    asset=self.asset,
                    user=staff,
                    description="El motor de la banda huele a quemado, avisó Juan Pérez.",
                )
            wait_for_delivery()

            body = server.raw_bodies()[0].decode("utf-8")
            for secret in [
                "Juan Pérez",
                "quemado",
                str(staff),
                self.supervisor.email,
                self.asset.name,
                self.company.name,
                TOKEN,
            ]:
                assert secret not in body, f"el payload filtró {secret!r}"

    def test_a_hanging_endpoint_neither_delays_nor_breaks_the_operation(self):
        """Acceptance criterion: with n8n hanging, the OT is still verified and
        the caller is not made to wait for the timeout."""
        work_order = self._verified_work_order()

        # The endpoint sleeps for as long as the client is willing to wait, so a
        # synchronous implementation would pay the full three seconds here.
        with RecordingWebhookServer(delay_seconds=3.0) as server:
            with override_settings(
                N8N_WEBHOOK_URL=server.url,
                N8N_WEBHOOK_TOKEN=TOKEN,
                N8N_WEBHOOK_TIMEOUT=3.0,
            ):
                # The clock starts *after* the transition, around the delivery
                # alone. The database in this project is a remote Supabase
                # instance and a transition costs about a second of network on
                # its own — timing the whole block would measure the latency of
                # the test environment, not whether anybody waits for n8n.
                with self.captureOnCommitCallbacks(execute=False) as callbacks:
                    workorder_services.transition(
                        work_order, workorder_services.VERIFY, self.supervisor
                    )
                started = time.monotonic()
                for callback in callbacks:
                    callback()
                elapsed = time.monotonic() - started

            work_order.refresh_from_db()
            assert work_order.status == WorkOrder.Status.VERIFICADA
            assert elapsed < 0.5, f"la operación esperó al webhook ({elapsed:.2f}s)"
            wait_for_delivery(timeout=10)

    def test_an_endpoint_that_answers_with_an_error_changes_nothing(self):
        work_order = self._verified_work_order()

        with RecordingWebhookServer(status=500) as server:
            with override_settings(
                N8N_WEBHOOK_URL=server.url, N8N_WEBHOOK_TOKEN=TOKEN
            ), self.captureOnCommitCallbacks(execute=True):
                workorder_services.transition(
                    work_order, workorder_services.VERIFY, self.supervisor
                )
            wait_for_delivery()

        work_order.refresh_from_db()
        assert work_order.status == WorkOrder.Status.VERIFICADA

    def test_a_redirect_never_carries_the_token_to_another_host(self):
        """urllib copies custom headers onto the request it follows a redirect
        with — including the token, and including across hosts. So redirects
        are not followed at all (apps/core/webhooks.py)."""
        work_order = self._verified_work_order()

        with RecordingWebhookServer() as attacker:
            with RecordingWebhookServer(redirect_to=attacker.url) as n8n:
                with override_settings(
                    N8N_WEBHOOK_URL=n8n.url, N8N_WEBHOOK_TOKEN=TOKEN
                ), self.captureOnCommitCallbacks(execute=True):
                    workorder_services.transition(
                        work_order, workorder_services.VERIFY, self.supervisor
                    )
                wait_for_delivery()

                assert len(n8n.received) == 1
            assert attacker.received == [], "el token siguió la redirección"

        work_order.refresh_from_db()
        assert work_order.status == WorkOrder.Status.VERIFICADA

    def test_a_dead_host_changes_nothing(self):
        """Nothing is listening on that port. The operation still succeeds."""
        work_order = self._verified_work_order()

        with override_settings(
            N8N_WEBHOOK_URL="http://127.0.0.1:9/n8n",
            N8N_WEBHOOK_TOKEN=TOKEN,
            N8N_WEBHOOK_TIMEOUT=0.2,
        ), self.captureOnCommitCallbacks(execute=True):
            workorder_services.transition(work_order, workorder_services.VERIFY, self.supervisor)
        wait_for_delivery()

        work_order.refresh_from_db()
        assert work_order.status == WorkOrder.Status.VERIFICADA


class EventCoverageTests(TestCase):
    """Each of the brief's four events fires where it should."""

    def setUp(self):
        self.company = CompanyFactory()
        self.staff = StaffUserFactory(company=self.company)
        self.supervisor = SupervisorUserFactory(company=self.company)
        self.asset = AssetFactory(company=self.company)

    def _events(self, callback):
        with RecordingWebhookServer() as server:
            with override_settings(
                N8N_WEBHOOK_URL=server.url, N8N_WEBHOOK_TOKEN=TOKEN
            ), self.captureOnCommitCallbacks(execute=True):
                callback()
            wait_for_delivery()
            return server.payloads()

    def test_reporting_a_failure_emits_solicitud_creada(self):
        payloads = self._events(
            lambda: request_services.create_request(
                asset=self.asset, user=self.staff, description="Se detuvo sola."
            )
        )

        assert [payload["evento"] for payload in payloads] == [
            webhooks.EVENT_REQUEST_CREATED
        ]

    def test_converting_a_request_emits_ot_creada(self):
        request_obj = request_services.create_request(
            asset=self.asset, user=self.staff, description="Se detuvo sola."
        )

        payloads = self._events(
            lambda: request_services.convert(request_obj, user=self.supervisor)
        )

        events = [payload["evento"] for payload in payloads]
        assert events == [webhooks.EVENT_WORK_ORDER_CREATED]
        assert payloads[0]["datos"]["solicitud_id"] == request_obj.pk
        assert payloads[0]["datos"]["origen"] == WorkOrder.Origin.SOLICITUD

    def test_the_scheduler_emits_one_ot_vencida_digest_per_company(self):
        """One message about forty late work orders, not forty messages."""
        yesterday = timezone.localdate() - timedelta(days=1)
        for _ in range(3):
            AssignedWorkOrderFactory(
                asset=self.asset, company=self.company, due_date=yesterday
            )

        payloads = self._events(
            lambda: maintenance_services.generate_for_company(self.company)
        )

        overdue = [
            payload
            for payload in payloads
            if payload["evento"] == webhooks.EVENT_WORK_ORDER_OVERDUE
        ]
        assert len(overdue) == 1
        assert overdue[0]["datos"]["total"] == 3
        assert len(overdue[0]["datos"]["ordenes"]) == 3
