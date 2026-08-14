from datetime import date, timedelta

import factory
from factory.django import DjangoModelFactory

from apps.accounts.models import Company, Site, Subscription, User


class CompanyFactory(DjangoModelFactory):
    class Meta:
        model = Company
        skip_postgeneration_save = True

    name = factory.Sequence(lambda n: f"Empresa {n}")
    nit = factory.Sequence(lambda n: f"900{n:06d}-1")
    is_active = True

    @factory.post_generation
    def subscription(self, create, extracted, **kwargs):
        if not create:
            return
        SubscriptionFactory(company=self, **kwargs)


class SubscriptionFactory(DjangoModelFactory):
    class Meta:
        model = Subscription

    company = factory.SubFactory(CompanyFactory)
    plan = Subscription.Plan.STANDARD
    status = Subscription.Status.ACTIVE
    max_assets = 50
    max_users = 5
    current_period_end = factory.LazyFunction(lambda: date.today() + timedelta(days=30))


class SiteFactory(DjangoModelFactory):
    class Meta:
        model = Site

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Planta {n}")
    address = "Zona Industrial"


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    company = factory.SubFactory(CompanyFactory)
    role = User.Role.TECHNICIAN
    is_active = True

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        # Unlike CompanyFactory's `subscription` hook, this one DOES mutate
        # `self` (set_password only sets self.password in memory — it never
        # saves). skip_postgeneration_save means factory_boy won't save
        # again after this runs, so the hook must save explicitly, or the
        # DB row keeps its unusable placeholder password forever: the login
        # session's auth hash (computed from the in-memory hashed password)
        # would then never match the DB's, and every request after the
        # first silently drops back to AnonymousUser.
        if not create:
            return
        self.set_password(extracted or "testpass123")
        self.save(update_fields=["password"])


class AdminUserFactory(UserFactory):
    role = User.Role.ADMIN


class SupervisorUserFactory(UserFactory):
    role = User.Role.SUPERVISOR


class TechnicianUserFactory(UserFactory):
    role = User.Role.TECHNICIAN


class StaffUserFactory(UserFactory):
    role = User.Role.STAFF


class PlatformAdminUserFactory(UserFactory):
    company = None
    role = ""
    is_platform_admin = True
    is_staff = True
    is_superuser = True
