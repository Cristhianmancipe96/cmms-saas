import uuid

from django.conf import settings
from django.db import models

from apps.accounts.models import Site
from apps.assets.storage import asset_document_upload_path, asset_photo_upload_path
from apps.core.tenancy import CompanyScopedModel


class AssetCategory(CompanyScopedModel):
    """A user-creatable machine type (e.g. "Empacadora", "Compresor")."""

    name = models.CharField("nombre", max_length=100)

    class Meta(CompanyScopedModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="assetcategory_unique_company_name"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Asset(CompanyScopedModel):
    class Criticality(models.TextChoices):
        ALTA = "alta", "Alta"
        MEDIA = "media", "Media"
        BAJA = "baja", "Baja"

    class Status(models.TextChoices):
        OPERATIVO = "operativo", "Operativo"
        DETENIDO = "detenido", "Detenido"
        DADO_DE_BAJA = "dado_de_baja", "Dado de baja"

    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="assets", verbose_name="sitio"
    )
    category = models.ForeignKey(
        AssetCategory, on_delete=models.PROTECT, related_name="assets", verbose_name="categoría"
    )
    code = models.CharField("código", max_length=50, help_text="Etiqueta interna del equipo.")
    qr_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    name = models.CharField("nombre", max_length=200)
    brand = models.CharField("marca", max_length=100, blank=True, default="")
    model = models.CharField("modelo", max_length=100, blank=True, default="")
    serial_number = models.CharField("número de serie", max_length=100, blank=True, default="")
    purchase_date = models.DateField("fecha de compra", null=True, blank=True)
    warranty_until = models.DateField("garantía hasta", null=True, blank=True)
    criticality = models.CharField(
        "criticidad", max_length=10, choices=Criticality.choices, default=Criticality.MEDIA
    )
    status = models.CharField(
        "estado", max_length=20, choices=Status.choices, default=Status.OPERATIVO
    )
    location_detail = models.CharField(
        "ubicación específica", max_length=200, blank=True, default=""
    )
    # Plain FileField on purpose: Django's ImageField runs its own Pillow
    # validation before AssetForm.clean_main_photo ever executes, producing
    # Django's generic built-in message instead of ours. storage.py already
    # verifies real image content (Image.verify()) and re-encodes it — a
    # second, uncontrolled validator would only produce inconsistent errors.
    main_photo = models.FileField(
        "foto principal", upload_to=asset_photo_upload_path, blank=True, null=True, max_length=255
    )
    specs = models.JSONField(
        "ficha técnica",
        default=list,
        blank=True,
        help_text="Lista ordenada de pares clave-valor: [{'key': ..., 'value': ...}].",
    )
    baja_reason = models.TextField("motivo de baja", blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(CompanyScopedModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="asset_unique_company_code")
        ]
        indexes = [*CompanyScopedModel.Meta.indexes, models.Index(fields=["qr_uuid"])]

    def __str__(self) -> str:
        return f"{self.code} · {self.name}"

    def has_documents(self) -> bool:
        # Not self.documents.exists(): that reverse relation is built on
        # AssetDocument's own CompanyScopedManager, which silently returns
        # empty outside a request context (contextvar unset — see
        # apps/core/tenancy.py). A deletion guard must hold from the shell,
        # a management command or a future Celery task too, not only from
        # the one HTTP view that happens to call it today.
        return AssetDocument.objects.unscoped().filter(asset=self).exists()

    def delete(self, *args, **kwargs):
        # Defense in depth: even a direct model/admin/shell call must not
        # wipe an asset that carries document history — not just the view.
        if self.has_documents():
            raise AssetHasDocumentsError(
                "No se puede eliminar un equipo con documentos adjuntos. "
                "Usa «Dar de baja» en su lugar."
            )
        return super().delete(*args, **kwargs)


class AssetHasDocumentsError(Exception):
    """Raised when an asset with attached documents is deleted. History is never wiped."""


class AssetDocument(CompanyScopedModel):
    class Kind(models.TextChoices):
        MANUAL = "manual", "Manual"
        GARANTIA = "garantia", "Garantía"
        CERTIFICADO = "certificado", "Certificado"
        OTRO = "otro", "Otro"

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices, default=Kind.OTRO)
    file = models.FileField(
        "archivo", upload_to=asset_document_upload_path, max_length=255
    )
    name = models.CharField("nombre", max_length=200)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta(CompanyScopedModel.Meta):
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return self.name
