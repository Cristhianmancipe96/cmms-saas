import factory

from apps.core.models import BootstrapPing


class BootstrapPingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BootstrapPing

    note = factory.Faker("word")
