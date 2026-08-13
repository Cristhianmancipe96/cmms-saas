# Brief 10 — Demo seeds, E2E smoke, polish

**Depends on:** 09.
**Goal:** the product demos itself: one command produces a believable company with
history, and a golden-path test proves the whole loop works.

## Build

1. Management command **`seed_demo`** (idempotent — safe to re-run, wipes and recreates
   only its own demo company). ALL DATA FICTIONAL (house rule):
   - Company "Empaques La Sabana S.A.S." (NIT ficticio), 2 sites (Planta Funza, Bodega
     Fontibón), subscription `active` plan `standard`.
   - Users (password `demo1234`, documented): 1 admin, 1 supervisor, 2 technicians,
     1 staff.
   - Categories: Empacadora flow-pack, Compresor, Banda transportadora, Selladora.
   - 8 assets — 3 Flowpac-style wrappers with realistic specs (velocidad máx paquetes/min,
     ancho de bobina, voltaje, presión de aire), photos optional placeholders, 1 asset
     `dado_de_baja`.
   - 2 checklist templates (Flowpac semanal — 8 items incl. 2 numeric with ranges;
     mensual — 12 items), one with a version-2 chain.
   - Plans: weekly + monthly on the Flowpacs, annual on compressor, one meter-based
     (every 250 h) with readings history.
   - **~90 days of history**: completed+verified preventive WOs (varied on-time/late for
     a realistic compliance ~80%), 6 corrective WOs with downtime and costs, 2 open
     overdue, 3 due this week, 2 pending requests, meter readings trail.
2. **E2E golden-path test** (Django test client, one class):
   login technician → open QR URL → execute due WO (fill checklist incl. one failing
   numeric, upload photo, complete) → login supervisor → verify WO → download WO PDF →
   email hoja de vida (locmem) → dashboard compliance reflects the new WO. Assert audit
   rows exist for each step.
3. **Polish pass** (Spanish, mobile): consistent empty states, nav (bottom bar on
   mobile), page titles, favicon, login screen with product name, human 403/404/500
   pages, Django admin restricted to `is_platform_admin`.
4. **README update**: quickstart (docker + uv + seed_demo + runserver), demo credentials
   table, feature list with checkmarks matching STATUS.md, 2–3 screenshots
   (`docs/screenshots/`, fictional data only).

## Out of scope

Deploy (brief 11), billing UI (Phase 3), n8n flows (Phase 2).

## Acceptance criteria

1. Fresh DB: `seed_demo` + full `pytest -q` green; command re-run leaves counts stable
   (idempotency test).
2. Golden-path E2E passes and covers: QR entry, checklist with failing numeric, photo,
   verify by non-executor, PDF bytes, email log, dashboard delta, audit rows.
3. Dashboard on seeded data shows non-trivial numbers (compliance between 60–95%,
   non-empty backlog buckets) — asserted in test.
4. Every seeded string is fictional; test asserts the seed module contains no real
   client names (grep guard for a small blocklist the owner provides).
5. Lighthouse-style sanity: technician home and execution screen usable at 390px (manual
   check documented with screenshots in the PR summary).
6. `is_platform_admin=False` users get 404/302 on `/admin/` (test).

## Definition of done

Per CLAUDE.md. Commit: `feat(demo): fictional seed company, golden-path E2E and UI polish`.
