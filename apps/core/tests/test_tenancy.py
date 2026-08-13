from contextlib import contextmanager

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts.models import Site
from apps.accounts.tests.factories import CompanyFactory, SiteFactory, UserFactory
from apps.core.middleware import CurrentCompanyMiddleware
from apps.core.tenancy import current_company_id


@contextmanager
def scoped_as(company):
    token = current_company_id.set(company.id if company else None)
    try:
        yield
    finally:
        current_company_id.reset(token)


class CompanyScopedManagerTests(TestCase):
    def test_default_manager_filters_by_current_company(self):
        company_a = CompanyFactory()
        company_b = CompanyFactory()
        site_a = SiteFactory(company=company_a)
        SiteFactory(company=company_b)

        with scoped_as(company_a):
            assert list(Site.objects.all()) == [site_a]

    def test_default_manager_returns_nothing_without_company_context(self):
        SiteFactory()

        with scoped_as(None):
            assert list(Site.objects.all()) == []

    def test_unscoped_bypasses_the_filter(self):
        SiteFactory()
        SiteFactory()

        with scoped_as(None):
            assert Site.objects.unscoped().count() == 2


class CurrentCompanyMiddlewareTests(TestCase):
    def test_sets_contextvar_from_authenticated_user_company(self):
        company = CompanyFactory()
        user = UserFactory(company=company)
        request = RequestFactory().get("/")
        request.user = user
        seen = {}

        def get_response(request):
            seen["company_id"] = current_company_id.get()
            return "ok"

        CurrentCompanyMiddleware(get_response)(request)

        assert seen["company_id"] == company.id
        assert current_company_id.get() is None

    def test_anonymous_user_resolves_to_none(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        seen = {}

        def get_response(request):
            seen["company_id"] = current_company_id.get()
            return "ok"

        CurrentCompanyMiddleware(get_response)(request)

        assert seen["company_id"] is None
