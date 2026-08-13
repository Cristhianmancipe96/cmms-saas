# Brief 11 — Security hardening and deploy readiness

**Depends on:** 10.
**Goal:** the owner's stated #1 priority made verifiable: hardened settings, abuse
resistance, and a written security posture before any real customer data enters.

## Build

1. **Login hardening**: django-axes (or equivalent) — lockout after 5 failed attempts
   per user+IP with Spanish lockout page and auto-reset window; log lockouts to
   AuditLog.
2. **Session/cookie policy**: `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SECURE` and
   `CSRF_COOKIE_SECURE` (prod), `SameSite=Lax`, session expiry 12 h with sliding
   refresh, logout invalidates.
3. **Production settings profile** passing `manage.py check --deploy` clean:
   `SECURE_HSTS_*`, `SECURE_SSL_REDIRECT`, `SECURE_PROXY_SSL_HEADER`,
   `X_FRAME_OPTIONS=DENY`, `SECURE_REFERRER_POLICY`, `ALLOWED_HOSTS` from env,
   `DEBUG=False` enforced (assert on startup when `ENV=production`).
4. **Password policy**: Django validators tuned (min length 10, common-password check);
   force temp-password change on first login (from brief 01 invites).
5. **Rate limiting** on sensitive endpoints (login, email-send, PDF generation) —
   simple per-user/IP throttle; Spanish 429 page.
6. **Dependency + config audit in CI**: `pip-audit` (or `uv` audit) job + `gitleaks`
   full-history scan job (not just pre-commit); CI fails on findings.
7. **Backups & data lifecycle doc** (`docs/security.md`): daily `pg_dump` recipe with
   restore steps (tested once, documented), media backup note, data retention and
   deletion-on-request policy (Ley 1581 habeas data), incident basics (rotate secrets,
   invalidate sessions), production checklist (env vars, HTTPS via reverse proxy,
   webhook secret rotation).
8. **Dockerfile** for the web app (non-root user, gunicorn) + compose `web` service —
   deploy-ready for a VPS/Railway; document the deploy path in `docs/security.md`.
   **The owner deploys; agents never touch production credentials.**

## Out of scope

Actual production deployment, penetration testing, WAF/CDN, SSO.

## Acceptance criteria

1. 6th failed login locks the account (test); lockout row in AuditLog; unlock after
   window (test with time travel).
2. `manage.py check --deploy` reports zero warnings under the production profile (test
   runs it programmatically).
3. Throttle test: >N rapid email-send/PDF requests → 429 Spanish page, no 500.
4. First-login temp password forces change before any other page loads (test).
5. CI includes pip-audit + full-history gitleaks jobs and both pass on `main`.
6. `docs/security.md` exists with backup/restore, retention (Ley 1581) and deploy
   checklist sections; `pg_dump`/restore commands are copy-pasteable.
7. Web Dockerfile builds and serves via gunicorn as non-root (CI job builds the image).

## Definition of done

Per CLAUDE.md. Commit: `feat(security): login hardening, deploy profile and security docs`.
