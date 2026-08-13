# Brief 06 — QR flow: live asset view by role

**Depends on:** 05.
**Goal:** a printed QR on every machine; scanning it shows the live record rendered by
the viewer's role — the owner's signature feature.

## Build

1. Public entry route **`/e/<qr_uuid>`** (uuid4 from brief 02):
   - Anonymous → login redirect preserving `next` (after login, land back on the asset).
   - Authenticated, **same company** → live view (below). Authenticated, other company →
     **404** (never reveal existence).
2. **Live view by role** (one template, role-conditional sections — server-rendered,
   current DB state):
   - **Técnico**: status card + THEIR open WOs on this asset with direct "ejecutar"
     buttons + quick meter-reading entry.
   - **Supervisor/Admin**: status card + open WOs (all), next due plan, last 5 completed
     interventions, quick actions (nueva OT correctiva, ver hoja de vida completa).
   - **Staff**: status card + read-only history summary.
   - Status card (all roles): asset name/code/photo, current status, criticality, open
     WO count, next preventive due date, last completed maintenance date.
3. **Label generation**: `qrcode` lib. Per-asset label (QR + code + name + company name)
   and an A4 sheet view to print labels for N selected assets (print CSS grid). QR
   encodes the absolute URL to `/e/<uuid>` (base URL from env `SITE_URL`).
4. Regenerate-UUID action (admin only, for compromised/reprinted labels) with
   confirmation — old QR must stop resolving (it's a new uuid).

## Out of scope

Native camera scanning UI (the phone's camera app scans and opens the URL), offline
mode, public/anonymous asset info.

## Acceptance criteria

1. Anonymous scan → login → lands on the asset view (test follows redirect chain).
2. Role rendering: technician sees only their own open WOs and the execute button;
   staff sees no action buttons; supervisor sees all open WOs (3 tests on the same
   asset with different logins).
3. User from another company gets 404 (test).
4. The label sheet renders one working QR per selected asset and encodes `SITE_URL`-based
   absolute URLs (decode the PNG in the test and assert the URL).
5. After regenerate-UUID, the old URL 404s and the new one resolves (test).
6. Asset primary keys never appear in the public URL — only the uuid (test asserts).

## Definition of done

Per CLAUDE.md. Commit: `feat(qr): per-asset QR labels and role-aware live view`.
