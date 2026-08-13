from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.tenancy import CompanyScopedModel


class Company(models.Model):
    name = models.CharField(max_length=200)
    nit = models.CharField("NIT", max_length=32, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Subscription(models.Model):
    class Plan(models.TextChoices):
        BASIC = "basic", "Básico"
        STANDARD = "standard", "Estándar"
        PRO = "pro", "Pro"

    class Status(models.TextChoices):
        TRIAL = "trial", "Prueba"
        ACTIVE = "active", "Activa"
        PAST_DUE = "past_due", "Pago vencido"
        SUSPENDED = "suspended", "Suspendida"

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="subscription")
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.BASIC)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    max_assets = models.PositiveIntegerField(default=50)
    max_users = models.PositiveIntegerField(default=5)
    current_period_end = models.DateField()

    def __str__(self) -> str:
        return f"{self.company} · {self.get_plan_display()} · {self.get_status_display()}"


class Site(CompanyScopedModel):
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255, blank=True, default="")

    class Meta(CompanyScopedModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrador"
        SUPERVISOR = "supervisor", "Supervisor"
        TECHNICIAN = "technician", "Técnico"
        STAFF = "staff", "Administrativo"

    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        help_text="Vacío solo para administradores de la plataforma.",
    )
    role = models.CharField(max_length=20, choices=Role.choices, blank=True, default="")
    whatsapp_phone = models.CharField(max_length=20, blank=True, default="")
    is_platform_admin = models.BooleanField(default=False)

    class Meta(AbstractUser.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(is_platform_admin=True) | models.Q(company__isnull=False),
                name="user_company_required_unless_platform_admin",
            )
        ]

    def __str__(self) -> str:
        return self.get_username()
