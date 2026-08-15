"""The delivery log is tenant data too, and it must not block a deletion.

The second half is the interesting one. `NotificationLog` points at an asset
and at a work order, so it joins the set of rows Django has to deal with when
either is deleted. `SET_NULL` is only a correct answer if it actually runs —
"the log kept a row alive that the equipment screen says it deleted" is exactly
the kind of silent failure that only shows up under a real delete.
"""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory
from apps.assets.models import Asset
from apps.assets.tests.factories import AssetFactory
from apps.core.tenancy import current_company_id
from apps.reports.models import NotificationLog
from apps.reports.tests.factories import NotificationLogFactory


class NotificationLogScopeTests(TestCase):
    def setUp(self):
        self.mine = CompanyFactory()
        self.theirs = CompanyFactory()
        self.my_row = NotificationLogFactory(company=self.mine, recipient="yo@mia.com")
        NotificationLogFactory(company=self.theirs, recipient="ellos@otra.com")

    def test_the_scoped_manager_only_returns_this_company(self):
        token = current_company_id.set(self.mine.pk)
        self.addCleanup(current_company_id.reset, token)

        rows = list(NotificationLog.objects.all())

        assert [row.pk for row in rows] == [self.my_row.pk]

    def test_with_no_tenant_set_the_manager_returns_nothing(self):
        token = current_company_id.set(None)
        self.addCleanup(current_company_id.reset, token)

        assert list(NotificationLog.objects.all()) == []
        assert NotificationLog.objects.unscoped().count() == 2


class DeletionTests(TestCase):
    """The log must never be the reason an equipment record cannot be deleted."""

    def setUp(self):
        self.company = CompanyFactory()
        self.asset = AssetFactory(company=self.company)
        self.row = NotificationLogFactory(company=self.company, asset=self.asset)
        self.admin = AdminUserFactory(company=self.company)
        self.client.force_login(self.admin)

    def test_deleting_the_equipment_leaves_the_log_row_orphaned_not_blocked(self):
        response = self.client.post(
            reverse("asset_delete", args=[self.asset.pk]), follow=True
        )

        assert response.status_code == 200
        assert not Asset.objects.unscoped().filter(pk=self.asset.pk).exists()

        self.row.refresh_from_db()
        assert self.row.asset_id is None
        assert self.row.recipient  # the record of the send itself survives
