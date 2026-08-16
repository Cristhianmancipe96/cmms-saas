"""The window every KPI is measured over.

One module, one job: turn the `?periodo=` value a browser sends into a pair of
timestamps. Every query in `queries.py` then takes that pair as bound
parameters — the period never reaches the SQL as text.

Two decisions live here rather than in each query, so they cannot drift:

1. **The window never extends into the future.** «Mes actual» and «Año en
   curso» end *now*, not on the 31st. A preventive work order scheduled for
   next week has not failed to happen yet, and counting it as non-compliant
   would make the current month look worse the earlier in the month you
   looked at it.
2. **Everything is resolved in America/Bogota** (`settings.TIME_ZONE`), the
   plant's own clock: "el mes" starts at midnight in Bogotá, not in UTC.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.utils import timezone

# `key` is what travels in the querystring; the label is what the operator
# reads in the switcher.
PERIOD_CHOICES: tuple[tuple[str, str], ...] = (
    ("mes", "Mes actual"),
    ("30d", "Últimos 30 días"),
    ("90d", "Últimos 90 días"),
    ("ano", "Año en curso"),
)

# A month is too short a base for MTBF on a plant with few failures, and a year
# too long to notice a bad week: 30 days is what a maintenance manager compares
# week over week.
DEFAULT_PERIOD = "30d"

_LABELS = dict(PERIOD_CHOICES)


@dataclass(frozen=True)
class Period:
    """A half-open window `[starts_at, ends_at)` plus how to name it."""

    key: str
    label: str
    starts_at: datetime
    ends_at: datetime

    @property
    def start_date(self) -> date:
        """First day covered — what `due_date` (a plain date) is compared to."""
        return timezone.localtime(self.starts_at).date()

    @property
    def end_date(self) -> date:
        """Last day covered, inclusive."""
        return timezone.localtime(self.ends_at).date()

    @property
    def minutes(self) -> Decimal:
        """Calendar minutes in the window — the denominator of availability.

        Computed again in SQL (`EXTRACT(EPOCH FROM …)`) so the database never
        depends on Python arithmetic; this copy exists for the tests, which
        hand-compute the expected numbers from it.
        """
        return Decimal((self.ends_at - self.starts_at).total_seconds()) / Decimal(60)


def resolve(key: str | None, *, now: datetime | None = None) -> Period:
    """The period for a querystring value. Never raises: an unknown key is the
    default, because a KPI screen must not 404 on a mistyped URL."""
    now = now or timezone.now()
    local_now = timezone.localtime(now)
    key = key if key in _LABELS else DEFAULT_PERIOD

    if key == "mes":
        starts_at = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif key == "ano":
        starts_at = local_now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    elif key == "90d":
        starts_at = local_now - timedelta(days=90)
    else:
        starts_at = local_now - timedelta(days=30)

    return Period(key=key, label=_LABELS[key], starts_at=starts_at, ends_at=local_now)
