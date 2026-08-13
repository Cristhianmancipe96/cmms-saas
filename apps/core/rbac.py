"""The single, shared way to gate a view by role.

Never write ad-hoc `if request.user.role == ...` checks in a view — use
`role_required` (function-based views) or `RoleRequiredMixin` (class-based
views) so every permission decision is auditable in one place.

`is_platform_admin` always passes a role check: it is an orthogonal,
cross-tenant elevation flag, independent of the four business roles.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render


def _role_allowed(user, roles):
    return user.is_platform_admin or user.role in roles


def deny(request):
    """The one Spanish 403 page every permission rejection renders."""
    return render(request, "core/403.html", status=403)


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not _role_allowed(request.user, roles):
                return deny(request)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


class RoleRequiredMixin:
    """CBV equivalent of `role_required`. Set `allowed_roles` on the view."""

    allowed_roles: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not _role_allowed(request.user, self.allowed_roles):
            return deny(request)
        return super().dispatch(request, *args, **kwargs)
