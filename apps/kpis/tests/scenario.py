"""One plant, one month, every number computed by hand.

This is the single source of truth the KPI tests assert against: `build()`
creates the work orders below for a company, and the `EXPECTED_*` constants
are what a maintenance manager would get with a calculator and the arithmetic
written out beside them. If a query and this file disagree, one of them is
wrong — and it is deliberately hard to make them wrong in the same direction,
because nothing here is computed, it is all written down.

Fixed dates, never `now() - 30 days`: the cost indicator groups by calendar
month, so a scenario anchored to the clock would split into two rows whenever
the suite ran near a month boundary and pass or fail depending on the day.

    Window:  2026-03-01 00:00  →  2026-03-31 00:00  (America/Bogota)
             exactly 30 days = 43 200 minutes per asset
    "Today"  for the backlog:  2026-03-31

    Equipos: E-01 (operativo) · E-02 (operativo) · E-03 (dado de baja)

    Correctivas
      C1  E-01  05/03 08:00 → 10:00   2 h   parada 120 min   $60 000 + $40 000
      C2  E-01  12/03 07:00 → 11:00   4 h   parada 240 min   $40 000 + $10 000
      C3  E-01  cancelada, parada 999 min, $999 999          → no cuenta
      C4  E-01  terminada el 20/02 (fuera de ventana)        → no cuenta

    Preventivas (vencen dentro de la ventana)
      P1  E-01  vence 06/03, cerrada 06/03      a tiempo
      P2  E-01  vence 18/03, cerrada 17/03      a tiempo
      P3  E-02  vence 10/03, cerrada 11/03      TARDE
      P4  E-01  vence 26/03, abierta            TARDE (nunca se hizo)
      P5  E-02  vence 20/03, cerrada 20/03      a tiempo · $30 000 mano de obra
      P6  E-01  vence 08/03, cancelada          → no cuenta
      P7  E-01  vence 10/02 (fuera de ventana)  → no cuenta

    Backlog al 31/03 (abiertas y vencidas)
      B1  E-01  vencía 21/03  asignada      10 días
      B2  E-02  vencía 01/03  en progreso   30 días
      B3  E-01  vencía 28/02  abierta       31 días
      B4  E-02  vencía 14/02  abierta       45 días
      B5  E-01  vence 05/04   abierta       → no vencida
      B6  E-02  vencía 02/03  terminada     → ya no es backlog
      + P4, que también está vencida (5 días)

Las cuentas
    Parada E-01 = 120 + 240 = 360 min      Parada E-02 = 0
    Operación E-01 = 43 200 − 360 = 42 840 min = 714 h
    Operación E-02 = 43 200 min = 720 h
    MTBF E-01 = 714 / 2 fallas = 357,00 h  ·  E-02 = sin fallas → «—»
    MTBF flota = (714 + 720) / 2 = 717,00 h
    MTTR = (2 h + 4 h) / 2 = 3,00 h
    Disponibilidad E-01 = 42 840 / 43 200 = 99,17 %  ·  E-02 = 100,00 %
    Disponibilidad flota = 86 040 / 86 400 = 99,58 %
    Cumplimiento = 3 a tiempo / 5 programadas = 60,00 %
    Backlog = 5 (1 de menos de 7 días · 2 de 7 a 30 · 2 de más de 30)
    Costo E-01 marzo = $150 000 · E-02 marzo = $30 000 · total $180 000
"""

from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

from apps.assets.models import Asset
from apps.assets.tests.factories import AssetFactory
from apps.kpis.periods import Period
from apps.workorders.models import WorkOrder
from apps.workorders.tests.factories import WorkOrderFactory


def at(day: int, hour: int = 0, minute: int = 0, month: int = 3) -> datetime:
    """A moment in the plant's own timezone, in 2026."""
    return timezone.make_aware(datetime(2026, month, day, hour, minute))


WINDOW = Period(
    key="mes",
    label="Marzo de 2026",
    starts_at=at(1),
    ends_at=at(31),
)
TODAY = date(2026, 3, 31)

WINDOW_MINUTES = Decimal("43200")

EXPECTED_MTBF_FLEET = Decimal("717.00")
EXPECTED_MTBF_E1 = Decimal("357.00")
EXPECTED_UPTIME_FLEET = Decimal("1434.00")
EXPECTED_FAILURES = 2
EXPECTED_MTTR = Decimal("3.00")
EXPECTED_MTTR_REPAIRS = 2
EXPECTED_COMPLIANCE = Decimal("60.00")
EXPECTED_COMPLIANCE_ON_TIME = 3
EXPECTED_COMPLIANCE_SCHEDULED = 5
EXPECTED_AVAILABILITY_FLEET = Decimal("99.58")
EXPECTED_AVAILABILITY_E1 = Decimal("99.17")
EXPECTED_AVAILABILITY_E2 = Decimal("100.00")
EXPECTED_DOWNTIME = 360
EXPECTED_BACKLOG_TOTAL = 5
EXPECTED_BACKLOG_UNDER_7 = 1
EXPECTED_BACKLOG_7_TO_30 = 2
EXPECTED_BACKLOG_OVER_30 = 2
EXPECTED_COST_E1 = 150_000
EXPECTED_COST_E2 = 30_000
EXPECTED_COST_TOTAL = 180_000


def build(company, site=None) -> dict[str, Asset]:
    """Create the scenario above for `company`. Returns its assets by code."""
    common = {"company": company}
    if site is not None:
        common["site"] = site

    e1 = AssetFactory(code="E-01", name="Empacadora 1", **common)
    e2 = AssetFactory(code="E-02", name="Compresor", **common)
    # Decommissioned: its history must not dilute the fleet's availability.
    e3 = AssetFactory(
        code="E-03", name="Sopladora vieja", status=Asset.Status.DADO_DE_BAJA, **common
    )

    def work_order(asset, **kwargs):
        return WorkOrderFactory(asset=asset, company=company, **kwargs)

    corrective = {"type": WorkOrder.Type.CORRECTIVO, "origin": WorkOrder.Origin.MANUAL}

    # --- Correctivas ------------------------------------------------------
    work_order(
        e1,
        **corrective,
        status=WorkOrder.Status.VERIFICADA,
        started_at=at(5, 8),
        finished_at=at(5, 10),
        downtime_minutes=120,
        labor_cost_cop=60_000,
        parts_cost_cop=40_000,
    )
    work_order(
        e1,
        **corrective,
        status=WorkOrder.Status.TERMINADA,
        started_at=at(12, 7),
        finished_at=at(12, 11),
        downtime_minutes=240,
        labor_cost_cop=40_000,
        parts_cost_cop=10_000,
    )
    # Cancelled: loud numbers that must not reach a single indicator.
    work_order(
        e1,
        **corrective,
        status=WorkOrder.Status.CANCELADA,
        started_at=at(15, 6),
        finished_at=at(15, 22),
        downtime_minutes=999,
        labor_cost_cop=999_999,
        parts_cost_cop=999_999,
    )
    # Before the window opens.
    work_order(
        e1,
        **corrective,
        status=WorkOrder.Status.TERMINADA,
        started_at=at(20, 8, month=2),
        finished_at=at(20, 18, month=2),
        downtime_minutes=600,
        labor_cost_cop=500_000,
    )

    # --- Preventivas ------------------------------------------------------
    work_order(
        e1, due_date=date(2026, 3, 6), status=WorkOrder.Status.TERMINADA, finished_at=at(6, 16)
    )
    work_order(
        e1, due_date=date(2026, 3, 18), status=WorkOrder.Status.VERIFICADA, finished_at=at(17, 9)
    )
    work_order(
        e2, due_date=date(2026, 3, 10), status=WorkOrder.Status.TERMINADA, finished_at=at(11, 9)
    )
    work_order(e1, due_date=date(2026, 3, 26), status=WorkOrder.Status.ABIERTA)
    work_order(
        e2,
        due_date=date(2026, 3, 20),
        status=WorkOrder.Status.TERMINADA,
        finished_at=at(20, 14),
        labor_cost_cop=30_000,
    )
    work_order(
        e1, due_date=date(2026, 3, 8), status=WorkOrder.Status.CANCELADA, finished_at=at(8, 10)
    )
    work_order(
        e1,
        due_date=date(2026, 2, 10),
        status=WorkOrder.Status.TERMINADA,
        finished_at=at(10, 11, month=2),
    )

    # --- Backlog ----------------------------------------------------------
    work_order(e1, **corrective, due_date=date(2026, 3, 21), status=WorkOrder.Status.ASIGNADA)
    work_order(e2, **corrective, due_date=date(2026, 3, 1), status=WorkOrder.Status.EN_PROGRESO)
    work_order(e1, **corrective, due_date=date(2026, 2, 28), status=WorkOrder.Status.ABIERTA)
    work_order(e2, **corrective, due_date=date(2026, 2, 14), status=WorkOrder.Status.ABIERTA)
    work_order(e1, **corrective, due_date=date(2026, 4, 5), status=WorkOrder.Status.ABIERTA)
    # Closed after the window: overdue once, but not backlog any more — and its
    # `finished_at` is outside the window, so it is not a failure either.
    work_order(
        e2,
        **corrective,
        due_date=date(2026, 3, 2),
        status=WorkOrder.Status.TERMINADA,
        started_at=at(1, 8, month=4),
        finished_at=at(1, 18, month=4),
    )

    return {"E-01": e1, "E-02": e2, "E-03": e3}
