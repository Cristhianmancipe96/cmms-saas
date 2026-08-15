import secrets
from urllib.parse import urljoin

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView, PasswordChangeDoneView, PasswordChangeView
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.accounts.forms import SiteForm, UserInviteForm
from apps.accounts.models import Site, Subscription, User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core.rbac import RoleRequiredMixin, deny, role_required
from apps.reports import emails, mailer
from apps.reports.models import NotificationLog

ALL_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN, User.Role.STAFF)
MANAGER_ROLES = (User.Role.ADMIN, User.Role.SUPERVISOR)

# What the audit log keeps about an account. Note what is absent and cannot be
# added by accident: `password` (and anything else whose name looks like a
# credential) is redacted by apps/audit/services.py itself, on the way in.
AUDITED_USER_FIELDS = ("username", "email", "role", "is_active")


class CompanyAuthLoginView(LoginView):
    template_name = "registration/login.html"

    def get_default_redirect_url(self):
        # Role-based dashboards arrive with later briefs; every role lands
        # on the home page for now.
        return reverse("home")


class CompanyPasswordChangeView(PasswordChangeView):
    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("password_change_done")


class CompanyPasswordChangeDoneView(PasswordChangeDoneView):
    template_name = "registration/password_change_done.html"


class SiteListView(RoleRequiredMixin, ListView):
    allowed_roles = ALL_ROLES
    model = Site
    template_name = "accounts/site_list.html"
    context_object_name = "sites"


class SiteDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = ALL_ROLES
    model = Site
    template_name = "accounts/site_detail.html"
    context_object_name = "site"


class SiteCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = MANAGER_ROLES
    model = Site
    form_class = SiteForm
    template_name = "accounts/site_form.html"

    def form_valid(self, form):
        # is_platform_admin bypasses the role gate above but has no company
        # of its own — this view has no "create for which company" selector,
        # so a companyless caller is out of scope here, not a crash.
        if self.request.user.company is None:
            return deny(self.request)
        form.instance.company = self.request.user.company
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("site_detail", args=[self.object.pk])


class SiteUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = MANAGER_ROLES
    model = Site
    form_class = SiteForm
    template_name = "accounts/site_form.html"

    def get_success_url(self):
        return reverse("site_detail", args=[self.object.pk])


@role_required(User.Role.ADMIN)
def user_list(request):
    company_users = User.objects.filter(company=request.user.company).order_by("username")
    return render(request, "accounts/user_list.html", {"company_users": company_users})


def _seats_full(company):
    return User.objects.filter(company=company).count() >= company.subscription.max_users


def _seats_full_message(company):
    return (
        f"Tu plan permite un máximo de {company.subscription.max_users} usuarios "
        "y ya lo alcanzaste. Actualiza tu plan para invitar a alguien más."
    )


@role_required(User.Role.ADMIN)
def user_invite(request):
    company = request.user.company
    # is_platform_admin bypasses the role gate above but has no company of
    # its own — there's no "invite for which company" selector here.
    if company is None:
        return deny(request)

    if request.method == "POST":
        form = UserInviteForm(request.POST)
        if form.is_valid():
            temp_password = secrets.token_urlsafe(9)
            with transaction.atomic():
                # Lock the subscription row so two concurrent invites for the
                # same company can't both pass the seat check before either
                # commits (plain count-then-create is a TOCTOU race).
                Subscription.objects.select_for_update().get(company=company)
                if _seats_full(company):
                    messages.error(request, _seats_full_message(company))
                    return redirect("user_list")
                user = form.save(commit=False)
                user.company = company
                user.set_password(temp_password)
                user.save()
                # Inside the atomic block on purpose: if the invitation mail
                # fails, the block rolls back, the account never existed — and
                # neither should a row claiming somebody created it.
                audit.record(
                    action=AuditLog.Action.CREATE,
                    instance=user,
                    user=request.user,
                    company=company,
                    changes=audit.created(user, AUDITED_USER_FIELDS),
                    request=request,
                )
                # Read out now: if the send fails the row below is rolled back
                # and `user` becomes a stale object with a pk that no longer
                # exists.
                username, address = user.get_username(), user.email
                subject, body = emails.temp_password_message(
                    user=user,
                    temp_password=temp_password,
                    company=company,
                    login_url=urljoin(settings.SITE_URL, reverse("login")),
                )
                delivery = mailer.deliver(recipient=address, subject=subject, body=body)
                if not delivery.ok:
                    # Brief 07 carry-over: the temporary password is never
                    # printed on screen any more, so the email IS the
                    # invitation. Undelivered, it would leave an account nobody
                    # can enter and a seat nobody can reclaim — and the
                    # password itself would exist only in a log line. Roll the
                    # whole invitation back and let the admin retry.
                    transaction.set_rollback(True)

            # Outside the block on purpose: the row recording a failed send has
            # to survive the rollback that failure just caused.
            mailer.log(
                delivery,
                company=company,
                kind=NotificationLog.Kind.TEMP_PASSWORD,
                sent_by=request.user,
            )

            if delivery.ok:
                messages.success(
                    request,
                    f"Usuario {username} creado. Le enviamos la contraseña "
                    f"temporal a {address}.",
                )
            else:
                messages.error(
                    request,
                    f"No se pudo enviar el correo a {address}, así que el usuario "
                    "no se creó. Revisa la configuración de correo e inténtalo "
                    "de nuevo.",
                )
            return redirect("user_list")
    else:
        form = UserInviteForm()
        if _seats_full(company):
            messages.error(request, _seats_full_message(company))
            return redirect("user_list")
    return render(request, "accounts/user_invite.html", {"form": form})


@role_required(User.Role.ADMIN)
def user_deactivate(request, pk):
    target = get_object_or_404(User, pk=pk, company=request.user.company)
    if request.method == "POST":
        before = audit.snapshot(target, AUDITED_USER_FIELDS)
        target.is_active = False
        target.save(update_fields=["is_active"])
        audit.record(
            action=AuditLog.Action.UPDATE,
            instance=target,
            user=request.user,
            company=target.company,
            changes=audit.diff(
                before, audit.snapshot(target, AUDITED_USER_FIELDS), instance=target
            ),
            request=request,
        )
        messages.success(request, f"Usuario {target.username} desactivado.")
        return redirect("user_list")
    return render(request, "accounts/user_deactivate_confirm.html", {"target": target})
