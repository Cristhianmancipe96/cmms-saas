"""The six maintenance indicators, each one hand-written SQL.

This is the only module in the product allowed to talk SQL (CLAUDE.md rule 7).
Everything else goes through the ORM, so the rules the ORM enforces for free
have to be enforced by hand here, on every single query:

- **`company_id = %s` in the WHERE of every query.** There is no scoped
  manager behind `connection.cursor()`: a forgotten predicate here is not a
  slow page, it is company A reading company B's plant. Where a query joins
  `assets_asset`, the company is asserted on *both* tables — a work order and
  its asset can only ever share a company, and the redundant predicate is what
  makes that assumption checkable instead of assumed.
- **Every value is a bound parameter.** No f-strings, no `%`, no `.format`,
  not even for something as innocent as a `LIMIT`. `test_sql_discipline.py`
  parses this file and fails the build if a query string is ever built rather
  than written.
- **Every ratio divides through `NULLIF(…, 0)`.** A company with no failures
  this month must get "no data" (SQL NULL → `None` → «—» on screen), never a
  `division by zero` that takes the whole dashboard down.

Two conventions shared by all six, so the numbers add up between cards:

- **A work order counts in the window by `finished_at`** — when the work was
  actually completed — except PM compliance, which is a question about
  *schedule* and therefore counts by `due_date`. Cancelled work orders never
  count anywhere.
- **Downtime is downtime, whoever caused it.** `downtime_minutes` from any
  work order (preventive stops included) is subtracted from operating time, so
  availability and MTBF cannot disagree about how long a machine was stopped.
  Only *corrective* orders count as failures.

The formulas are restated in Spanish, for the operator, in `docs/kpis.md`.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import connection

from apps.kpis.periods import Period

# How many rows the two "worst offenders" tables show. A bound parameter like
# any other value — never interpolated into the LIMIT.
TOP_N = 10


def _run(sql: str, params: list[Any]) -> list[tuple]:
    """Execute one parameterized statement and return its rows.

    The single place a cursor is opened, so "params are always bound" is one
    call signature to audit rather than eight.
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


# --- The shared window ------------------------------------------------------
#
# Every per-asset query below opens with the same two CTEs, written out in
# full in each one rather than assembled from fragments: a query you can copy
# into psql and run is evidence an auditor can check, and string-built SQL is
# exactly what this module promises never to do.
#
#   win    — the window, plus its length in minutes, from two bound timestamps.
#   scope  — the assets the numbers are about: this company's, still in
#            service, optionally narrowed to one site. `COALESCE(%s, site_id)`
#            is the "todas las sedes" case in one parameter instead of two.


# --- 1. MTBF ----------------------------------------------------------------

SQL_MTBF = """
-- MTBF — «¿cuánto aguanta el equipo entre fallas?»
-- Operating hours in the window ÷ corrective work orders in the window.
-- Operating hours = calendar hours − recorded downtime, floored at zero.
-- GROUPING SETS returns the per-asset rows and the fleet row (asset_id NULL)
-- in one pass: the fleet number is total uptime ÷ total failures, never the
-- average of the per-asset averages.
WITH win AS (
    SELECT starts_at,
           ends_at,
           EXTRACT(EPOCH FROM (ends_at - starts_at)) / 60.0 AS minutes
    FROM (SELECT %s::timestamptz AS starts_at, %s::timestamptz AS ends_at) AS bounds
),
scope AS (
    SELECT a.id, a.code, a.name
    FROM assets_asset a
    WHERE a.company_id = %s
      AND a.status <> 'dado_de_baja'
      AND a.site_id = COALESCE(%s::integer, a.site_id)
),
per_asset AS (
    SELECT s.id   AS asset_id,
           s.code AS code,
           s.name AS name,
           win.minutes AS window_minutes,
           COUNT(wo.id) FILTER (WHERE wo.type = 'correctivo') AS failures,
           COALESCE(SUM(wo.downtime_minutes), 0) AS downtime_minutes
    FROM scope s
    CROSS JOIN win
    LEFT JOIN workorders_workorder wo
           ON wo.asset_id = s.id
          AND wo.company_id = %s
          AND wo.status <> 'cancelada'
          AND wo.finished_at >= win.starts_at
          AND wo.finished_at <  win.ends_at
    GROUP BY s.id, s.code, s.name, win.minutes
)
SELECT p.asset_id,
       p.code,
       p.name,
       COALESCE(SUM(p.failures), 0)::int AS failures,
       ROUND(COALESCE(SUM(GREATEST(p.window_minutes - p.downtime_minutes, 0)), 0) / 60.0,
             2) AS uptime_hours,
       ROUND(SUM(GREATEST(p.window_minutes - p.downtime_minutes, 0)) / 60.0
             / NULLIF(SUM(p.failures), 0), 2) AS mtbf_hours,
       GROUPING(p.asset_id) AS is_fleet
FROM per_asset p
GROUP BY GROUPING SETS ((p.asset_id, p.code, p.name), ())
ORDER BY GROUPING(p.asset_id) DESC, mtbf_hours ASC NULLS LAST, p.code
"""


@dataclass(frozen=True)
class AssetMtbf:
    asset_id: int
    code: str
    name: str
    failures: int
    uptime_hours: Decimal
    hours: Decimal | None


@dataclass(frozen=True)
class Mtbf:
    """Fleet MTBF plus the per-asset breakdown behind it."""

    hours: Decimal | None
    failures: int
    uptime_hours: Decimal
    by_asset: list[AssetMtbf]


def mtbf(company_id: int, period: Period, site_id: int | None = None) -> Mtbf:
    rows = _run(
        SQL_MTBF,
        [period.starts_at, period.ends_at, company_id, site_id, company_id],
    )
    fleet = next((r for r in rows if r[6] == 1), None)
    return Mtbf(
        hours=fleet[5] if fleet else None,
        failures=fleet[3] if fleet else 0,
        uptime_hours=(fleet[4] if fleet and fleet[4] is not None else Decimal("0.00")),
        by_asset=[
            AssetMtbf(
                asset_id=row[0],
                code=row[1],
                name=row[2],
                failures=row[3],
                uptime_hours=row[4],
                hours=row[5],
            )
            for row in rows
            if row[6] == 0
        ],
    )


# --- 2. MTTR ----------------------------------------------------------------

SQL_MTTR = """
-- MTTR — «¿cuánto tardamos en repararlo?»
-- Average of (finished_at − started_at) over the corrective work orders
-- finished in the window. Orders without both timestamps are not repairs with
-- an unknown duration, they are repairs whose duration was never recorded:
-- averaging them in as zero would flatter the number, so they are excluded.
-- AVG over zero rows is NULL, so there is no denominator to guard here.
SELECT COUNT(*)::int AS repairs,
       ROUND(AVG(EXTRACT(EPOCH FROM (wo.finished_at - wo.started_at)) / 3600.0),
             2) AS mttr_hours
FROM workorders_workorder wo
JOIN assets_asset a
  ON a.id = wo.asset_id
 AND a.company_id = %s
WHERE wo.company_id = %s
  AND wo.type = 'correctivo'
  AND wo.status <> 'cancelada'
  AND wo.started_at IS NOT NULL
  AND wo.finished_at IS NOT NULL
  AND wo.finished_at >= %s
  AND wo.finished_at <  %s
  AND a.site_id = COALESCE(%s::integer, a.site_id)
"""


@dataclass(frozen=True)
class Mttr:
    hours: Decimal | None
    repairs: int


def mttr(company_id: int, period: Period, site_id: int | None = None) -> Mttr:
    rows = _run(
        SQL_MTTR,
        [company_id, company_id, period.starts_at, period.ends_at, site_id],
    )
    repairs, hours = rows[0]
    return Mttr(hours=hours, repairs=repairs)


# --- 3. PM compliance -------------------------------------------------------

SQL_PM_COMPLIANCE = """
-- Cumplimiento del plan preventivo — «¿hicimos a tiempo lo programado?»
-- Preventive work orders closed on or before their due date ÷ preventive work
-- orders due in the window. Counted by `due_date`, not by `finished_at`: the
-- question is about the schedule, so an order due in the window and never
-- touched has to weigh against us — which it only does if the denominator is
-- "what was scheduled".
-- `finished_at` is compared in the plant's own timezone: a repair closed at
-- 20:00 in Bogotá is 01:00 UTC the next day, and would otherwise read as late.
WITH scheduled AS (
    SELECT (
               wo.status IN ('terminada', 'verificada')
               AND wo.finished_at IS NOT NULL
               AND (wo.finished_at AT TIME ZONE %s::text)::date <= wo.due_date
           ) AS on_time
    FROM workorders_workorder wo
    JOIN assets_asset a
      ON a.id = wo.asset_id
     AND a.company_id = %s
    WHERE wo.company_id = %s
      AND wo.type = 'preventivo'
      AND wo.status <> 'cancelada'
      AND wo.due_date IS NOT NULL
      AND wo.due_date >= %s
      AND wo.due_date <= %s
      AND a.site_id = COALESCE(%s::integer, a.site_id)
)
SELECT COUNT(*)::int AS scheduled,
       COUNT(*) FILTER (WHERE on_time)::int AS on_time,
       ROUND(100.0 * COUNT(*) FILTER (WHERE on_time) / NULLIF(COUNT(*), 0),
             2) AS compliance_pct
FROM scheduled
"""


@dataclass(frozen=True)
class PmCompliance:
    percent: Decimal | None
    on_time: int
    scheduled: int


def pm_compliance(company_id: int, period: Period, site_id: int | None = None) -> PmCompliance:
    rows = _run(
        SQL_PM_COMPLIANCE,
        [
            settings.TIME_ZONE,
            company_id,
            company_id,
            period.start_date,
            period.end_date,
            site_id,
        ],
    )
    scheduled, on_time, percent = rows[0]
    return PmCompliance(percent=percent, on_time=on_time, scheduled=scheduled)


# --- 4. Availability --------------------------------------------------------

SQL_AVAILABILITY = """
-- Disponibilidad — «¿qué porcentaje del tiempo estuvo el equipo en pie?»
-- (calendar minutes − downtime) ÷ calendar minutes, per asset and for the
-- fleet, from `downtime_minutes` as the technician recorded it.
-- Calendar time, not shift time: the product does not know the plant's shifts
-- yet, and inventing them here would make the number unauditable.
-- GREATEST(…, 0) is the guard for a mistyped downtime longer than the window —
-- that is bad data to correct, never a negative availability on a dashboard.
WITH win AS (
    SELECT starts_at,
           ends_at,
           EXTRACT(EPOCH FROM (ends_at - starts_at)) / 60.0 AS minutes
    FROM (SELECT %s::timestamptz AS starts_at, %s::timestamptz AS ends_at) AS bounds
),
scope AS (
    SELECT a.id, a.code, a.name
    FROM assets_asset a
    WHERE a.company_id = %s
      AND a.status <> 'dado_de_baja'
      AND a.site_id = COALESCE(%s::integer, a.site_id)
),
per_asset AS (
    SELECT s.id   AS asset_id,
           s.code AS code,
           s.name AS name,
           win.minutes AS window_minutes,
           COALESCE(SUM(wo.downtime_minutes), 0) AS downtime_minutes
    FROM scope s
    CROSS JOIN win
    LEFT JOIN workorders_workorder wo
           ON wo.asset_id = s.id
          AND wo.company_id = %s
          AND wo.status <> 'cancelada'
          AND wo.finished_at >= win.starts_at
          AND wo.finished_at <  win.ends_at
    GROUP BY s.id, s.code, s.name, win.minutes
)
SELECT p.asset_id,
       p.code,
       p.name,
       COALESCE(SUM(p.downtime_minutes), 0)::bigint AS downtime_minutes,
       ROUND(100.0 * SUM(GREATEST(p.window_minutes - p.downtime_minutes, 0))
             / NULLIF(SUM(p.window_minutes), 0), 2) AS availability_pct,
       GROUPING(p.asset_id) AS is_fleet
FROM per_asset p
GROUP BY GROUPING SETS ((p.asset_id, p.code, p.name), ())
ORDER BY GROUPING(p.asset_id) DESC, availability_pct ASC NULLS LAST, p.code
"""


@dataclass(frozen=True)
class AssetAvailability:
    asset_id: int
    code: str
    name: str
    downtime_minutes: int
    percent: Decimal | None


@dataclass(frozen=True)
class Availability:
    percent: Decimal | None
    downtime_minutes: int
    by_asset: list[AssetAvailability]


def availability(company_id: int, period: Period, site_id: int | None = None) -> Availability:
    rows = _run(
        SQL_AVAILABILITY,
        [period.starts_at, period.ends_at, company_id, site_id, company_id],
    )
    fleet = next((r for r in rows if r[5] == 1), None)
    return Availability(
        percent=fleet[4] if fleet else None,
        downtime_minutes=fleet[3] if fleet else 0,
        by_asset=[
            AssetAvailability(
                asset_id=row[0],
                code=row[1],
                name=row[2],
                downtime_minutes=row[3],
                percent=row[4],
            )
            for row in rows
            if row[5] == 0
        ],
    )


# --- 5. Backlog -------------------------------------------------------------
#
# The only indicator that ignores the period switcher, and deliberately: an
# order that fell due three months ago and is still open is backlog *today*,
# whatever window the screen is showing. Ageing is measured from `due_date` to
# the current date in Bogotá, both bound parameters.

SQL_BACKLOG_BUCKETS = """
-- Backlog — «¿cuánto trabajo vencido tenemos encima, y desde cuándo?»
-- Open work orders (abierta/asignada/en progreso) whose due date has passed,
-- split into ageing buckets. A finished order is never backlog, even if it
-- was closed late — that is the compliance number's business, not this one.
WITH overdue AS (
    SELECT (%s::date - wo.due_date) AS days_late
    FROM workorders_workorder wo
    JOIN assets_asset a
      ON a.id = wo.asset_id
     AND a.company_id = %s
    WHERE wo.company_id = %s
      AND wo.status IN ('abierta', 'asignada', 'en_progreso')
      AND wo.due_date IS NOT NULL
      AND wo.due_date < %s::date
      AND a.site_id = COALESCE(%s::integer, a.site_id)
)
SELECT COUNT(*)::int AS total,
       COUNT(*) FILTER (WHERE days_late < 7)::int AS under_7,
       COUNT(*) FILTER (WHERE days_late BETWEEN 7 AND 30)::int AS from_7_to_30,
       COUNT(*) FILTER (WHERE days_late > 30)::int AS over_30
FROM overdue
"""

SQL_BACKLOG_ROWS = """
-- The oldest of that backlog, named — a bucket count tells a supervisor there
-- is a problem, this tells them which machine to walk to. Same predicates as
-- the bucket query above, so the list can never disagree with the counts.
SELECT wo.id,
       a.code,
       a.name,
       wo.due_date,
       (%s::date - wo.due_date)::int AS days_late,
       CASE
           WHEN (%s::date - wo.due_date) < 7  THEN 'menos_7'
           WHEN (%s::date - wo.due_date) <= 30 THEN 'de_7_a_30'
           ELSE 'mas_30'
       END AS bucket,
       wo.priority,
       wo.type
FROM workorders_workorder wo
JOIN assets_asset a
  ON a.id = wo.asset_id
 AND a.company_id = %s
WHERE wo.company_id = %s
  AND wo.status IN ('abierta', 'asignada', 'en_progreso')
  AND wo.due_date IS NOT NULL
  AND wo.due_date < %s::date
  AND a.site_id = COALESCE(%s::integer, a.site_id)
ORDER BY wo.due_date ASC, wo.id ASC
LIMIT %s
"""

# What each bucket is called on screen, and the severity it wears. Kept beside
# the SQL that produces the keys so a renamed bucket breaks in one file.
BACKLOG_BUCKETS: tuple[tuple[str, str, str], ...] = (
    ("menos_7", "Menos de 7 días", "warning"),
    ("de_7_a_30", "Entre 7 y 30 días", "warning"),
    ("mas_30", "Más de 30 días", "danger"),
)


@dataclass(frozen=True)
class BacklogRow:
    work_order_id: int
    asset_code: str
    asset_name: str
    due_date: date
    days_late: int
    bucket: str
    priority: str
    type: str


@dataclass(frozen=True)
class Backlog:
    total: int
    under_7: int
    from_7_to_30: int
    over_30: int
    rows: list[BacklogRow]

    def bucket_counts(self) -> list[tuple[str, int, str]]:
        """(label, count, severity) — what the ageing table renders."""
        counts = {"menos_7": self.under_7, "de_7_a_30": self.from_7_to_30, "mas_30": self.over_30}
        return [(label, counts[key], severity) for key, label, severity in BACKLOG_BUCKETS]


def backlog(
    company_id: int, today: date, site_id: int | None = None, limit: int = TOP_N
) -> Backlog:
    total, under_7, from_7_to_30, over_30 = _run(
        SQL_BACKLOG_BUCKETS,
        [today, company_id, company_id, today, site_id],
    )[0]
    rows = _run(
        SQL_BACKLOG_ROWS,
        [today, today, today, company_id, company_id, today, site_id, limit],
    )
    return Backlog(
        total=total,
        under_7=under_7,
        from_7_to_30=from_7_to_30,
        over_30=over_30,
        rows=[
            BacklogRow(
                work_order_id=row[0],
                asset_code=row[1],
                asset_name=row[2],
                due_date=row[3],
                days_late=row[4],
                bucket=row[5],
                priority=row[6],
                type=row[7],
            )
            for row in rows
        ],
    )


# --- 6. Cost per asset and month --------------------------------------------

SQL_COST_BY_ASSET_MONTH = """
-- Costo por equipo y mes — «¿en qué máquina se nos va la plata?»
-- Labour + parts of the work orders finished in the window, grouped by asset
-- and by calendar month (in Bogotá: a job closed at 19:00 on the 31st belongs
-- to that month, not to the next one in UTC), ranked, top N.
-- `SUM(…) OVER ()` is computed before the LIMIT, so every row carries the
-- period's *whole* cost — the top ten and the total come out of one query and
-- cannot disagree.
WITH costed AS (
    SELECT a.id   AS asset_id,
           a.code AS code,
           a.name AS name,
           date_trunc('month', wo.finished_at AT TIME ZONE %s::text)::date AS month,
           COALESCE(wo.labor_cost_cop, 0) AS labor_cop,
           COALESCE(wo.parts_cost_cop, 0) AS parts_cop
    FROM workorders_workorder wo
    JOIN assets_asset a
      ON a.id = wo.asset_id
     AND a.company_id = %s
    WHERE wo.company_id = %s
      AND wo.status <> 'cancelada'
      AND wo.finished_at >= %s
      AND wo.finished_at <  %s
      AND a.site_id = COALESCE(%s::integer, a.site_id)
      AND (wo.labor_cost_cop IS NOT NULL OR wo.parts_cost_cop IS NOT NULL)
),
totals AS (
    SELECT asset_id,
           code,
           name,
           month,
           SUM(labor_cop)::bigint AS labor_cop,
           SUM(parts_cop)::bigint AS parts_cop,
           SUM(labor_cop + parts_cop)::bigint AS total_cop
    FROM costed
    GROUP BY asset_id, code, name, month
)
SELECT asset_id,
       code,
       name,
       month,
       labor_cop,
       parts_cop,
       total_cop,
       RANK() OVER (ORDER BY total_cop DESC)::int AS position,
       SUM(total_cop) OVER ()::bigint AS period_total_cop
FROM totals
ORDER BY total_cop DESC, code ASC
LIMIT %s
"""


@dataclass(frozen=True)
class CostRow:
    asset_id: int
    code: str
    name: str
    month: date
    labor_cop: int
    parts_cop: int
    total_cop: int
    position: int


@dataclass(frozen=True)
class Cost:
    total_cop: int
    rows: list[CostRow]


def cost_by_asset_month(
    company_id: int, period: Period, site_id: int | None = None, limit: int = TOP_N
) -> Cost:
    rows = _run(
        SQL_COST_BY_ASSET_MONTH,
        [
            settings.TIME_ZONE,
            company_id,
            company_id,
            period.starts_at,
            period.ends_at,
            site_id,
            limit,
        ],
    )
    return Cost(
        # No rows means no costs recorded, which is zero pesos — not "unknown".
        total_cop=rows[0][8] if rows else 0,
        rows=[
            CostRow(
                asset_id=row[0],
                code=row[1],
                name=row[2],
                month=row[3],
                labor_cop=row[4],
                parts_cop=row[5],
                total_cop=row[6],
                position=row[7],
            )
            for row in rows
        ],
    )
