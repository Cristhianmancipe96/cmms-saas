from django.test import TestCase

from apps.accounts.tests.factories import CompanyFactory, UserFactory
from apps.checklists.models import ChecklistTemplate, ChecklistTemplateItem
from apps.checklists.tests.factories import ChecklistTemplateFactory, ChecklistTemplateItemFactory
from apps.workorders.tests.factories import lock_template


def _staffer_without_platform_admin(company):
    """Same shape as apps/accounts/tests/test_admin.py's helper — an
    is_staff (+ is_superuser) account reaching /admin/ without being a
    platform admin. This is exactly who Finding 1 of the immutability
    review showed could otherwise bypass services.py entirely.
    """
    return UserFactory(
        company=company,
        role="admin",
        is_staff=True,
        is_superuser=True,
        is_platform_admin=False,
    )


class ChecklistTemplateItemInlineIsReadOnlyTests(TestCase):
    """CLAUDE.md rule 4: item edits must always go through services.py so a
    locked template forks instead of mutating audit evidence. Django admin's
    inline formset save path calls instance.save() directly and never
    touches services.py — the inline must therefore be read-only, full
    stop, not just when the template happens to be locked.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.template = ChecklistTemplateFactory(company=self.company, version=1)
        self.item = ChecklistTemplateItemFactory(
            template=self.template, order=1, text="ORIGINAL TEXT"
        )
        self.staffer = _staffer_without_platform_admin(self.company)
        self.client.force_login(self.staffer)

    def _change_url(self):
        return f"/admin/checklists/checklisttemplate/{self.template.pk}/change/"

    def test_changeform_renders_item_fields_as_disabled_not_editable_inputs(self):
        response = self.client.get(self._change_url())

        assert response.status_code == 200
        content = response.content.decode()
        # A genuinely editable inline text input for this item would render
        # as <input ... name="checklisttemplateitem_set-0-text" ... value=
        # "ORIGINAL TEXT">. Django renders read-only inline fields as plain
        # text instead, so that editable input must not appear at all.
        assert 'name="checklisttemplateitem_set-0-text"' not in content

    def test_posting_an_edited_item_via_the_inline_formset_does_not_mutate_a_locked_item(self):
        lock_template(self.template)
        management_form = {
            "checklisttemplateitem_set-TOTAL_FORMS": "1",
            "checklisttemplateitem_set-INITIAL_FORMS": "1",
            "checklisttemplateitem_set-MIN_NUM_FORMS": "0",
            "checklisttemplateitem_set-MAX_NUM_FORMS": "1000",
            "checklisttemplateitem_set-0-id": str(self.item.pk),
            "checklisttemplateitem_set-0-template": str(self.template.pk),
            "checklisttemplateitem_set-0-order": "1",
            "checklisttemplateitem_set-0-text": "EDITED VIA ADMIN WHILE LOCKED",
            "checklisttemplateitem_set-0-item_type": "check",
            "checklisttemplateitem_set-0-unit": "",
            "name": self.template.name,
            "version": "1",
            "is_active": "on",
        }

        self.client.post(self._change_url(), management_form)

        reloaded_item = ChecklistTemplateItem.objects.unscoped().get(pk=self.item.pk)
        assert reloaded_item.text == "ORIGINAL TEXT"
        assert reloaded_item.template_id == self.template.pk
        # No fork was created either — the inline can't reach get_editable_version.
        assert ChecklistTemplate.objects.unscoped().filter(parent=self.template).count() == 0

    def test_posting_an_edited_item_via_the_inline_formset_does_not_mutate_an_unlocked_item(
        self,
    ):
        management_form = {
            "checklisttemplateitem_set-TOTAL_FORMS": "1",
            "checklisttemplateitem_set-INITIAL_FORMS": "1",
            "checklisttemplateitem_set-MIN_NUM_FORMS": "0",
            "checklisttemplateitem_set-MAX_NUM_FORMS": "1000",
            "checklisttemplateitem_set-0-id": str(self.item.pk),
            "checklisttemplateitem_set-0-template": str(self.template.pk),
            "checklisttemplateitem_set-0-order": "1",
            "checklisttemplateitem_set-0-text": "EDITED VIA ADMIN",
            "checklisttemplateitem_set-0-item_type": "check",
            "checklisttemplateitem_set-0-unit": "",
            "name": self.template.name,
            "version": "1",
            "is_active": "on",
        }

        self.client.post(self._change_url(), management_form)

        reloaded_item = ChecklistTemplateItem.objects.unscoped().get(pk=self.item.pk)
        assert reloaded_item.text == "ORIGINAL TEXT"
