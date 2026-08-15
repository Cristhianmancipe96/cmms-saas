import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import CompanyFactory, SupervisorUserFactory
from apps.audit.models import AuditLog


class AuditLogFactory(DjangoModelFactory):
    class Meta:
        model = AuditLog

    company = factory.SubFactory(CompanyFactory)
    user = factory.SubFactory(SupervisorUserFactory, company=factory.SelfAttribute("..company"))
    actor_label = factory.LazyAttribute(lambda o: str(o.user))
    action = AuditLog.Action.UPDATE
    model_label = "assets.Asset"
    object_id = 1
    object_repr = "COMP-01 — Compresor"
    changes = factory.LazyFunction(dict)
