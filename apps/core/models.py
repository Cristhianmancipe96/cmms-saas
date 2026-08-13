from django.db import models


class BootstrapPing(models.Model):
    """Bootstrap-only: proves the ORM round-trips against a real Postgres database.

    No business meaning — later briefs introduce the actual domain models.
    """

    note = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.note or f"ping #{self.pk}"
