from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CompanyFactory,
    StaffUserFactory,
    SupervisorUserFactory,
    TechnicianUserFactory,
)
from apps.checklists.tests.factories import ChecklistTemplateFactory, ChecklistTemplateItemFactory

MANAGER_FACTORIES = (AdminUserFactory, SupervisorUserFactory)
READONLY_FACTORIES = (TechnicianUserFactory, StaffUserFactory)


class ChecklistTemplateRoleMatrixTests(TestCase):
    """Acceptance criterion 6: admin/supervisor manage; technician/staff are
    read-only.
    """

    def setUp(self):
        self.company = CompanyFactory()
        self.template = ChecklistTemplateFactory(company=self.company)
        self.item = ChecklistTemplateItemFactory(template=self.template, order=1)

    def _login_as(self, factory_cls):
        user = factory_cls(company=self.company)
        self.client.force_login(user)
        return user

    def test_create_allows_admin_and_supervisor(self):
        for factory_cls in MANAGER_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("checklisttemplate_create"))
                assert response.status_code == 200
                self.client.logout()

    def test_create_blocks_technician_and_staff(self):
        for factory_cls in READONLY_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("checklisttemplate_create"))
                assert response.status_code == 403
                assert "No tienes permiso" in response.content.decode()
                self.client.logout()

    def test_item_create_allows_admin_and_supervisor(self):
        for factory_cls in MANAGER_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("checklistitem_create", args=[self.template.pk]))
                assert response.status_code == 200
                self.client.logout()

    def test_item_create_blocks_technician_and_staff(self):
        for factory_cls in READONLY_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(reverse("checklistitem_create", args=[self.template.pk]))
                assert response.status_code == 403
                self.client.logout()

    def test_item_update_blocks_technician_and_staff(self):
        for factory_cls in READONLY_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.get(
                    reverse("checklistitem_update", args=[self.template.pk, self.item.pk])
                )
                assert response.status_code == 403
                self.client.logout()

    def test_move_blocks_technician_and_staff(self):
        for factory_cls in READONLY_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                response = self.client.post(
                    reverse("checklistitem_move_down", args=[self.template.pk, self.item.pk])
                )
                assert response.status_code == 403
                self.client.logout()

    def test_all_roles_can_read_list_and_detail(self):
        for factory_cls in (*MANAGER_FACTORIES, *READONLY_FACTORIES):
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                list_response = self.client.get(reverse("checklisttemplate_list"))
                detail_response = self.client.get(
                    reverse("checklisttemplate_detail", args=[self.template.pk])
                )
                assert list_response.status_code == 200
                assert detail_response.status_code == 200
                self.client.logout()

    def test_duplicate_and_deactivate_block_technician_and_staff(self):
        for factory_cls in READONLY_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                self._login_as(factory_cls)
                duplicate_response = self.client.post(
                    reverse("checklisttemplate_duplicate", args=[self.template.pk])
                )
                deactivate_response = self.client.post(
                    reverse("checklisttemplate_deactivate", args=[self.template.pk])
                )
                assert duplicate_response.status_code == 403
                assert deactivate_response.status_code == 403
                self.client.logout()

    def test_duplicate_and_deactivate_allow_admin_and_supervisor(self):
        for factory_cls in MANAGER_FACTORIES:
            with self.subTest(factory=factory_cls.__name__):
                template = ChecklistTemplateFactory(company=self.company)
                self._login_as(factory_cls)
                duplicate_response = self.client.post(
                    reverse("checklisttemplate_duplicate", args=[template.pk])
                )
                assert duplicate_response.status_code == 302
                self.client.logout()
