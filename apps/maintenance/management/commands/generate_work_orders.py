"""Daily scheduler entry point. Safe to run as often as you like.

Designed for a once-a-day cron, but idempotent by construction (CLAUDE.md
rule 5), so re-running it after a failure, or twice by accident, creates
nothing new. Scheduling it is documented in README.md for both Linux cron
and Windows Task Scheduler.
"""

from django.core.management.base import BaseCommand

from apps.maintenance import services


class Command(BaseCommand):
    help = "Generates the preventive work orders due today (idempotent; run daily)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--horizon",
            type=int,
            default=0,
            metavar="DAYS",
            help=(
                "Also generate work orders due within this many days "
                "(default 0: only what is due today or overdue)."
            ),
        )

    def handle(self, *args, **options):
        horizon_days = options["horizon"]
        if horizon_days < 0:
            self.stderr.write("--horizon cannot be negative.")
            return

        total, per_company = services.generate_work_orders(horizon_days=horizon_days)

        for company, result in per_company:
            self.stdout.write(f"{company.name}: {result.as_line()}")
        self.stdout.write(self.style.SUCCESS(f"TOTAL — {total.as_line()}"))
