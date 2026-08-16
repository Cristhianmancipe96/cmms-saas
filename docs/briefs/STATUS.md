# Brief status

Tick a brief only when its Definition of Done is fully met (tests green, pushed).
Execute in order — each brief depends on all previous ones unless noted.

- [x] 00 — Bootstrap: Django skeleton, Postgres, CI, first push
- [x] 01 — Tenancy, accounts and roles
- [x] 02 — Assets (equipment records)
- [x] 03 — Checklist templates with versioning
- [x] 04 — Maintenance plans and idempotent scheduler
- [x] 05 — Work orders: state machine and mobile execution
- [x] 06 — QR flow: live asset view by role
- [x] 07 — PDFs (asset record, work-order report) and email
- [x] 08 — Failure requests, audit log, n8n webhook stub
- [x] 09 — Dashboard and KPIs in raw SQL
- [x] 10 — Demo seeds, E2E smoke, polish
- [x] 11 — Deploy readiness: production profile, Docker + gunicorn, backups, gitleaks in CI
- [ ] 11b — Remaining hardening: login lockout, rate limiting, password policy, pip-audit,
      Ley 1581 retention/deletion

Brief 11 was split by the owner on 2026-08-16: selling comes before completing the phases,
and a QR only sells when a prospect scans it with their own phone — which needs a public
HTTPS URL. The delivered half is everything required to be exposed to the internet with
fictional data. The pending half (11b) is specified in `11-security-hardening.md` items
1, 4, 5, 6 and part of 7, and is required **before any real customer data is loaded**.
