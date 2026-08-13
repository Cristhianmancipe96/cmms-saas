# Brief 01 — Tenancy, accounts and roles

**Depends on:** 00.
**Goal:** the multi-tenant + RBAC foundation every other brief stands on.

## Build

1. `apps/accounts`: **Company** (name, nit, is_active), **Subscription** (company 1-1,
   plan `basic/standard/pro`, status `trial/active/past_due/suspended`, max_assets,
   max_users, current_period_end), **Site** (company FK, name, address).
2. **Custom User** (`AUTH_USER_MODEL`, extends AbstractUser): company FK (nullable only
   for platform admins), `role` in `admin/supervisor/technician/staff`, `whatsapp_phone`,
   `is_platform_admin`.
3. **Tenant scoping machinery** in `apps/core`:
   - `CompanyScopedModel` abstract (company FK, indexes) + `CompanyScopedManager` whose
     default queryset filters by the current request's company.
   - Middleware storing current company (from `request.user`) in a contextvar; platform
     admin bypass must be explicit (`objects.unscoped()`), never the default.
   - `role_required(*roles)` decorator + CBV mixin, returning 403 with a Spanish page.
4. **Auth screens** (Spanish, mobile-first): login, logout, password change. After login
   route by role (all to `/` for now).
5. **User management** for company `admin`: list/invite (create with temp password)/
   deactivate users of their own company; enforce `subscription.max_users` on create.
6. **Suspension middleware**: users of a `suspended` company get a Spanish "empresa
   suspendida" screen (403) everywhere except logout.
7. Factories: CompanyFactory (with active subscription), SiteFactory, UserFactory
   (per-role helpers).

## Out of scope

Self-service signup, billing/payments, password reset by email (Phase 3), any asset model.

## Acceptance criteria

1. **Isolation:** with companies A and B seeded, every list/detail/edit URL of A's
   objects returns 404 for B's users (test hits real URLs).
2. Default manager on a scoped model NEVER returns other-company rows, even in naive
   code (`Model.objects.all()` in a view context) — test proves it.
3. `role_required` blocks each role correctly (matrix test) with a 403 Spanish page.
4. A `suspended` company's user is blocked on any page; `active`/`trial` pass.
5. Creating a user beyond `max_users` fails with a clear Spanish message.
6. Platform admin can access cross-company only via explicit `unscoped()` code path.
7. Login/logout work; role routing test.

## Definition of done

Per CLAUDE.md. Commit: `feat(accounts): multi-tenant core, custom user and RBAC`.
