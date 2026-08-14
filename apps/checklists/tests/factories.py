import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import CompanyFactory
from apps.assets.tests.factories import AssetCategoryFactory
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem


class ChecklistTemplateFactory(DjangoModelFactory):
    class Meta:
        model = ChecklistTemplate

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Plantilla {n}")
    category = factory.SubFactory(AssetCategoryFactory, company=factory.SelfAttribute("..company"))
    version = 1
    is_active = True
    parent = None


class ChecklistTemplateItemFactory(DjangoModelFactory):
    class Meta:
        model = ChecklistTemplateItem

    company = factory.SelfAttribute("template.company")
    template = factory.SubFactory(ChecklistTemplateFactory)
    order = factory.Sequence(lambda n: n + 1)
    text = factory.Sequence(lambda n: f"Verificar punto {n}")
    item_type = ChecklistTemplateItem.ItemType.CHECK
    unit = ""
    min_value = None
    max_value = None
    required = True


def create_flowpac_inspeccion_semanal(company=None, **kwargs) -> ChecklistTemplate:
    """A realistic template for reuse in tests and future seeds (brief 03,
    build item 5): weekly inspection of a Flowpac packaging machine.
    """
    template = ChecklistTemplateFactory(
        company=company, name="Flowpac inspección semanal", **kwargs
    )
    ChecklistTemplateItemFactory(
        template=template,
        order=1,
        text="Verificar nivel de aceite",
        item_type=ChecklistTemplateItem.ItemType.CHECK,
    )
    ChecklistTemplateItemFactory(
        template=template,
        order=2,
        text="Presión de aire de la línea",
        item_type=ChecklistTemplateItem.ItemType.NUMERIC,
        unit="bar",
        min_value=5,
        max_value=7,
    )
    ChecklistTemplateItemFactory(
        template=template,
        order=3,
        text="Observaciones generales",
        item_type=ChecklistTemplateItem.ItemType.TEXT,
    )
    return template
