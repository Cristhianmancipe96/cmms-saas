"""The delivery log: every message this product tries to send leaves a row.

One table for every channel on purpose. Email is the only one today; brief 08's
webhook and Phase 2's WhatsApp are the same question ("did the customer
actually receive it?") asked about a different transport, and an auditor
reading "se le envió el informe al supervisor el 14/08" should not have to know
which subsystem carried it.

A failed send is logged exactly like a successful one. A log that only records
what worked answers the easy question.
"""

from django.conf import settings
from django.db import models

from apps.core.tenancy import CompanyScopedModel


class NotificationLog(CompanyScopedModel):
    class Channel(models.TextChoices):
        EMAIL = "email", "Correo"

    class Kind(models.TextChoices):
        ASSET_RECORD = "hoja_de_vida", "Hoja de vida"
        WORK_ORDER_REPORT = "informe_ot", "Informe de OT"
        TEMP_PASSWORD = "credenciales", "Contraseña temporal"

    class Status(models.TextChoices):
        SENT = "enviado", "Enviado"
        FAILED = "fallido", "Fallido"

    channel = models.CharField(
        "canal", max_length=20, choices=Channel.choices, default=Channel.EMAIL
    )
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices)
    # Not a ForeignKey to User: the address is what was actually written on the
    # envelope. A user who later changes their email must not silently rewrite
    # the record of where a document was delivered last quarter.
    recipient = models.CharField("destinatario", max_length=254)
    subject = models.CharField("asunto", max_length=255)
    # SET_NULL, not CASCADE: "we emailed this to someone" stays true even after
    # the equipment record is gone, and the log is not itself audit evidence
    # worth blocking a delete over (that is what PROTECT on work orders is for).
    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.SET_NULL,
        related_name="notifications",
        verbose_name="equipo",
        null=True,
        blank=True,
    )
    work_order = models.ForeignKey(
        "workorders.WorkOrder",
        on_delete=models.SET_NULL,
        related_name="notifications",
        verbose_name="orden de trabajo",
        null=True,
        blank=True,
    )
    status = models.CharField("estado", max_length=20, choices=Status.choices)
    error_detail = models.TextField("detalle del error", blank=True, default="")
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="enviado por",
        null=True,
        blank=True,
    )
    sent_at = models.DateTimeField("fecha de envío", auto_now_add=True)

    class Meta(CompanyScopedModel.Meta):
        verbose_name = "envío"
        verbose_name_plural = "envíos"
        ordering = ["-sent_at", "-id"]
        indexes = [
            *CompanyScopedModel.Meta.indexes,
            models.Index(fields=["-sent_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} → {self.recipient} ({self.status})"

    @property
    def failed(self) -> bool:
        return self.status == self.Status.FAILED
