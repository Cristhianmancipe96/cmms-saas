from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory
from apps.assets.tests.factories import AssetCategoryFactory
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem
from apps.checklists.tests.factories import ChecklistTemplateFactory, ChecklistTemplateItemFactory
from apps.workorders.tests.factories import lock_template


class ChecklistTemplateCreateViewTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.category = AssetCategoryFactory(company=self.company)
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)

    def test_create_persists_template_as_version_1_active(self):
        response = self.client.post(
            reverse("checklisttemplate_create"),
            {"name": "Inspección diaria", "category": self.category.pk},
        )

        assert response.status_code == 302
        template = ChecklistTemplate.objects.unscoped().get(name="Inspección diaria")
        assert template.version == 1
        assert template.is_active is True
        assert template.company_id == self.company.pk

    def test_create_without_category_is_allowed(self):
        response = self.client.post(reverse("checklisttemplate_create"), {"name": "Sin categoría"})

        assert response.status_code == 302
        template = ChecklistTemplate.objects.unscoped().get(name="Sin categoría")
        assert template.category_id is None


class ChecklistItemBuilderViewTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)
        self.template = ChecklistTemplateFactory(company=self.company)

    def test_add_item_on_unused_template_mutates_in_place(self):
        response = self.client.post(
            reverse("checklistitem_create", args=[self.template.pk]),
            {"text": "Verificar guardas", "item_type": "check", "required": "on"},
        )

        assert response.status_code == 302
        assert response.url == reverse("checklisttemplate_detail", args=[self.template.pk])
        reloaded = ChecklistTemplate.objects.unscoped().get(pk=self.template.pk)
        assert reloaded.version == 1
        assert ChecklistTemplateItem.objects.unscoped().filter(template=reloaded).count() == 1

    def test_add_numeric_item_with_invalid_range_is_rejected_in_spanish(self):
        response = self.client.post(
            reverse("checklistitem_create", args=[self.template.pk]),
            {
                "text": "Presión",
                "item_type": "numeric",
                "unit": "bar",
                "min_value": "10",
                "max_value": "5",
                "required": "on",
            },
        )

        assert response.status_code == 200
        assert "mínimo" in response.content.decode().lower()
        assert ChecklistTemplateItem.objects.unscoped().filter(template=self.template).count() == 0

    def test_add_numeric_item_without_unit_is_rejected_in_spanish(self):
        response = self.client.post(
            reverse("checklistitem_create", args=[self.template.pk]),
            {
                "text": "Presión",
                "item_type": "numeric",
                "min_value": "1",
                "max_value": "5",
                "required": "on",
            },
        )

        assert response.status_code == 200
        assert "unidad" in response.content.decode().lower()

    def test_add_numeric_item_with_valid_range_succeeds(self):
        response = self.client.post(
            reverse("checklistitem_create", args=[self.template.pk]),
            {
                "text": "Presión",
                "item_type": "numeric",
                "unit": "bar",
                "min_value": "5",
                "max_value": "7",
                "required": "on",
            },
        )

        assert response.status_code == 302
        assert ChecklistTemplateItem.objects.unscoped().filter(template=self.template).count() == 1

    def test_reorder_persists_through_http(self):
        item_1 = ChecklistTemplateItemFactory(template=self.template, order=1, text="Uno")
        item_2 = ChecklistTemplateItemFactory(template=self.template, order=2, text="Dos")

        response = self.client.post(
            reverse("checklistitem_move_down", args=[self.template.pk, item_1.pk])
        )

        assert response.status_code == 302
        reloaded_1 = ChecklistTemplateItem.objects.unscoped().get(pk=item_1.pk)
        reloaded_2 = ChecklistTemplateItem.objects.unscoped().get(pk=item_2.pk)
        assert reloaded_1.order == 2
        assert reloaded_2.order == 1

    def test_move_up_via_get_is_not_allowed(self):
        item = ChecklistTemplateItemFactory(template=self.template, order=1)

        response = self.client.get(
            reverse("checklistitem_move_up", args=[self.template.pk, item.pk])
        )

        assert response.status_code == 405

    def test_editing_a_locked_template_redirects_to_the_new_version_and_parent_is_untouched(
        self,
    ):
        item = ChecklistTemplateItemFactory(template=self.template, order=1, text="Original")
        lock_template(self.template)

        response = self.client.post(
            reverse("checklistitem_update", args=[self.template.pk, item.pk]),
            {"text": "Editado", "item_type": "check", "required": "on"},
        )

        assert response.status_code == 302
        assert response.url != reverse("checklisttemplate_detail", args=[self.template.pk])

        parent = ChecklistTemplate.objects.unscoped().get(pk=self.template.pk)
        assert parent.is_active is False
        assert parent.version == 1
        parent_item = ChecklistTemplateItem.objects.unscoped().get(pk=item.pk)
        assert parent_item.text == "Original"

        new_version = ChecklistTemplate.objects.unscoped().get(parent=self.template)
        assert new_version.version == 2
        new_item = ChecklistTemplateItem.objects.unscoped().get(template=new_version)
        assert new_item.text == "Editado"

    def test_duplicate_creates_a_new_independent_template(self):
        ChecklistTemplateItemFactory(template=self.template, order=1)

        response = self.client.post(reverse("checklisttemplate_duplicate", args=[self.template.pk]))

        assert response.status_code == 302
        duplicate = ChecklistTemplate.objects.unscoped().get(name=f"{self.template.name} (copia)")
        assert duplicate.version == 1
        assert duplicate.parent is None

    def test_deactivate_flips_is_active(self):
        response = self.client.post(
            reverse("checklisttemplate_deactivate", args=[self.template.pk])
        )

        assert response.status_code == 302
        reloaded = ChecklistTemplate.objects.unscoped().get(pk=self.template.pk)
        assert reloaded.is_active is False
