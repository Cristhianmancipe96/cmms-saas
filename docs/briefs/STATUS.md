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
- [x] 11c — Visual hierarchy pass: equipment detail, KPI dashboard, mobile execution,
      lists and login; plus the leaked-template-comment bug and its regression test
- [x] 11d — Desktop shell and mobile navigation: sidebar with grouped nav and account
      menu, mobile hamburger with an icon sprite, page headers, full-width metric strip,
      dense desktop rows, segmented period control, two-column login

Brief 11 was split by the owner on 2026-08-16: selling comes before completing the phases,
and a QR only sells when a prospect scans it with their own phone — which needs a public
HTTPS URL. The delivered half is everything required to be exposed to the internet with
fictional data. The pending half (11b) is specified in `11-security-hardening.md` items
1, 4, 5, 6 and part of 7, and is required **before any real customer data is loaded**.

Brief 11c arrived by chat, not as a `docs/briefs/11c-*.md` file (the chat brief governs
per `CLAUDE.md`). It shipped in two commits: 11c-1 (multi-line `{# #}` comments rendering
as literal text and, on narrow viewports, overlapping buttons) was escalated mid-session
to a functional blocker on the deployed instance, so that fix landed alone first
(`da9bd8a`) for an immediate redeploy; the 11c-2 visual redesign — equipment detail,
KPI dashboard, mobile execution, lists, login — followed in its own commit.

Brief 11d arrived by chat too, after the owner tried the deployed app on his own phone
and computer: mobile got two named fixes (hamburger nav, icons); desktop got a
structural rewrite toward the sidebar/header/metric-row pattern of Tallaje, the owner's
other product (`C:\Users\andre\dev\tallaje`) — adapted, not copied (see docs/design/
DESIGN.md for what was kept and what wasn't). Interface only, same rule as 11c: nothing
in a `services.py`, `queries.py`, model or migration changed. Two pieces named in the
brief were not built — per-status tab counters for OTs and Solicitudes — because they
would have needed exactly that kind of change; flagged in DESIGN.md's "What did not
ship" instead of guessed at.
