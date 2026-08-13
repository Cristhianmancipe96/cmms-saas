from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.tests.factories import CompanyFactory


class UserCompanyConstraintTests(TestCase):
    def test_regular_user_without_company_is_rejected(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            User.objects.create(username="sin_empresa", role=User.Role.STAFF)

    def test_platform_admin_without_company_is_allowed(self):
        user = User.objects.create(
            username="root", is_platform_admin=True, is_staff=True, is_superuser=True
        )

        assert user.company_id is None

    def test_regular_user_with_company_is_allowed(self):
        company = CompanyFactory()

        user = User.objects.create(username="con_empresa", company=company, role=User.Role.STAFF)

        assert user.company_id == company.id
