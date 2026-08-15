"""An audit row is written once and never again — by any door.

The brief's «jamás se edita ni se borra (ni por queryset, ni por admin de
Django)» is four separate doors, so it is four separate tests: the instance,
the queryset, the admin, and the deliberate absence of any URL that would ask.
"""

import pytest
from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory
from apps.audit.models import AuditLog, AuditLogImmutable
from apps.audit.tests.factories import AuditLogFactory


class ModelGuardTests(TestCase):
    def setUp(self):
        self.company = CompanyFactory()
        self.entry = AuditLogFactory(company=self.company)

    def test_a_second_save_is_refused(self):
        self.entry.object_repr = "otra cosa"

        with pytest.raises(AuditLogImmutable):
            self.entry.save()

        self.entry.refresh_from_db()
        assert self.entry.object_repr == "COMP-01 — Compresor"

    def test_a_save_with_update_fields_is_refused_too(self):
        """The narrow spelling of the same write. A guard that only watches the
        wide one is not a guard."""
        self.entry.action = AuditLog.Action.DELETE

        with pytest.raises(AuditLogImmutable):
            self.entry.save(update_fields=["action"])

    def test_deleting_the_instance_is_refused(self):
        with pytest.raises(AuditLogImmutable):
            self.entry.delete()

        assert AuditLog.objects.unscoped().filter(pk=self.entry.pk).exists()

    def test_a_queryset_update_is_refused(self):
        """`queryset.update()` goes straight to SQL and never calls `save()`,
        which is exactly why the queryset carries its own refusal."""
        with pytest.raises(AuditLogImmutable):
            AuditLog.objects.unscoped().filter(pk=self.entry.pk).update(object_repr="x")

        self.entry.refresh_from_db()
        assert self.entry.object_repr == "COMP-01 — Compresor"

    def test_a_queryset_delete_is_refused(self):
        with pytest.raises(AuditLogImmutable):
            AuditLog.objects.unscoped().filter(pk=self.entry.pk).delete()

        assert AuditLog.objects.unscoped().filter(pk=self.entry.pk).exists()

    def test_an_empty_queryset_delete_is_refused_as_well(self):
        """No "well, it would not have deleted anything anyway" exception: the
        refusal is about the operation, not about how much damage it happens to
        do this time."""
        with pytest.raises(AuditLogImmutable):
            AuditLog.objects.unscoped().filter(pk=0).delete()


class AdminGuardTests(TestCase):
    """The Django admin is a door too, and a superuser walks through it."""

    def setUp(self):
        from django.contrib import admin

        self.admin_class = admin.site._registry[AuditLog]

    def test_the_admin_offers_no_add_change_or_delete(self):
        assert self.admin_class.has_add_permission(None) is False
        assert self.admin_class.has_change_permission(None) is False
        assert self.admin_class.has_delete_permission(None) is False


class NoWriteUrlsTests(TestCase):
    """There is exactly one audit URL, and it is a GET."""

    def test_posting_to_the_audit_list_changes_nothing(self):
        company = CompanyFactory()
        entry = AuditLogFactory(company=company)
        self.client.force_login(AdminUserFactory(company=company))

        response = self.client.post(reverse("auditlog_list"), {"delete": entry.pk})

        assert AuditLog.objects.unscoped().filter(pk=entry.pk).exists()
        # A ListView answers a POST with 405; either way, the row is still here.
        assert response.status_code in (200, 405)
