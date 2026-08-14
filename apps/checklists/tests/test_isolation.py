from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory
from apps.checklists.tests.factories import ChecklistTemplateFactory, ChecklistTemplateItemFactory


class ChecklistTemplateTenantIsolationTests(TestCase):
    """Acceptance criterion 5: company B gets 404 (never 403, never the
    actual data) on company A's template URLs.
    """

    def setUp(self):
        self.company_a = CompanyFactory()
        self.company_b = CompanyFactory()
        self.template_a = ChecklistTemplateFactory(company=self.company_a, name="Plantilla A")
        self.template_b = ChecklistTemplateFactory(company=self.company_b, name="Plantilla B")
        self.item_b = ChecklistTemplateItemFactory(template=self.template_b, order=1)
        self.admin_a = AdminUserFactory(company=self.company_a)
        self.client.force_login(self.admin_a)

    def test_detail_of_other_company_template_is_404(self):
        response = self.client.get(reverse("checklisttemplate_detail", args=[self.template_b.pk]))

        assert response.status_code == 404

    def test_item_create_on_other_company_template_is_404(self):
        response = self.client.get(reverse("checklistitem_create", args=[self.template_b.pk]))

        assert response.status_code == 404

    def test_item_update_on_other_company_template_is_404(self):
        response = self.client.get(
            reverse("checklistitem_update", args=[self.template_b.pk, self.item_b.pk])
        )

        assert response.status_code == 404

    def test_move_up_on_other_company_template_is_404(self):
        response = self.client.post(
            reverse("checklistitem_move_up", args=[self.template_b.pk, self.item_b.pk])
        )

        assert response.status_code == 404

    def test_duplicate_of_other_company_template_is_404(self):
        response = self.client.post(
            reverse("checklisttemplate_duplicate", args=[self.template_b.pk])
        )

        assert response.status_code == 404

    def test_deactivate_of_other_company_template_is_404(self):
        response = self.client.post(
            reverse("checklisttemplate_deactivate", args=[self.template_b.pk])
        )

        assert response.status_code == 404

    def test_own_company_template_is_reachable(self):
        response = self.client.get(reverse("checklisttemplate_detail", args=[self.template_a.pk]))

        assert response.status_code == 200

    def test_list_view_never_returns_other_company_rows(self):
        response = self.client.get(reverse("checklisttemplate_list"))
        content = response.content.decode()

        assert self.template_a.name in content
        assert self.template_b.name not in content


class ChecklistTemplateAnonymousAccessTests(TestCase):
    """Anonymous requests redirect to login — no bytes served, no 403
    leaking that the object exists.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.template = ChecklistTemplateFactory(company=self.company)

    def test_anonymous_detail_redirects_to_login(self):
        response = self.client.get(reverse("checklisttemplate_detail", args=[self.template.pk]))

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))

    def test_anonymous_list_redirects_to_login(self):
        response = self.client.get(reverse("checklisttemplate_list"))

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))
