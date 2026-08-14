from decimal import Decimal

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import CompanyFactory
from apps.assets.tests.factories import AssetFactory
from apps.maintenance.models import MaintenancePlan, MeterReading


class MaintenancePlanFactory(DjangoModelFactory):
    """A weekly calendar plan by default — the most common shape."""

    class Meta:
        model = MaintenancePlan

    company = factory.SubFactory(CompanyFactory)
    asset = factory.SubFactory(AssetFactory, company=factory.SelfAttribute("..company"))
    name = factory.Sequence(lambda n: f"Preventivo semanal {n}")
    kind = MaintenancePlan.Kind.PREVENTIVO
    frequency_type = MaintenancePlan.FrequencyType.CALENDAR
    interval_days = 7
    meter_interval_hours = None
    next_due_date = factory.LazyFunction(timezone.localdate)
    estimated_minutes = 60
    is_active = True


class MeterPlanFactory(MaintenancePlanFactory):
    """The other half of the model: generation driven by an hour meter."""

    name = factory.Sequence(lambda n: f"Cambio de aceite por horas {n}")
    frequency_type = MaintenancePlan.FrequencyType.METER
    interval_days = None
    next_due_date = None
    meter_interval_hours = Decimal("100.00")
    hours_at_last_generated_wo = Decimal("0.00")


class MeterReadingFactory(DjangoModelFactory):
    class Meta:
        model = MeterReading

    company = factory.SelfAttribute("asset.company")
    asset = factory.SubFactory(AssetFactory)
    reading_hours = Decimal("100.00")
    source = MeterReading.Source.MANUAL
