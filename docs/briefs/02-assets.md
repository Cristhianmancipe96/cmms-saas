# Brief 02 — Assets (equipment records / "hojas de vida")

**Depends on:** 01.
**Goal:** any machine type can be registered with a flexible technical sheet, photos and
documents — the digital "hoja de vida".

## Build

1. `apps/assets`: **AssetCategory** (company-scoped, name — user-creatable machine
   types), **Asset** (company-scoped): site FK, category FK, `code` (internal tag),
   `qr_uuid` (UUID4, unique, indexed, never exposed as sequential id), name, brand,
   model, serial_number, purchase_date, warranty_until, criticality (`alta/media/baja`),
   status (`operativo/detenido/dado_de_baja`), location_detail, main photo,
   **`specs` JSONB** (ordered key→value technical sheet), timestamps + created_by.
   **AssetDocument**: asset FK, kind (`manual/garantia/certificado/otro`), file, name.
2. Constraints: `UNIQUE(company, code)`; `qr_uuid` globally unique.
3. **CRUD, Spanish, mobile-first, HTMX**: searchable/filterable list (site, category,
   status, criticality); detail = hoja de vida (ficha + specs + documentos + fotos;
   "historial" tab as placeholder for brief 05); create/edit with dynamic specs rows
   (HTMX add/remove key-value); soft "dar de baja" action (status change with reason —
   assets are never hard-deleted once they have history).
4. **File security** (per CLAUDE.md): photos and documents stored under a non-guessable
   path and served ONLY via an auth+tenant-checked download view; uploads validated
   (whitelist jpg/png/webp/pdf, max 10 MB); images re-encoded with Pillow.
5. Permissions: admin/supervisor create+edit; technician and staff read-only.
6. Factories: AssetCategoryFactory, AssetFactory (realistic Flowpac-style specs),
   AssetDocumentFactory.

## Out of scope

QR generation/scan view (brief 06), maintenance history content (brief 05), meters
(brief 04).

## Acceptance criteria

1. Two companies can both have an asset coded `FLOW-01`; within one company the code is
   unique (test).
2. A user of company B gets 404 on company A's asset detail, edit and document URLs;
   fetching a document file URL of another company returns 404 — the file bytes are
   never served (test).
3. Anonymous requests to a document/photo URL redirect to login — no bytes served (test).
4. Technician/staff receive 403 on create/edit; admin/supervisor succeed (matrix test).
5. An upload with a forbidden extension or >10 MB is rejected with a Spanish message.
6. Specs survive a create→edit round-trip preserving key order.
7. An asset with any document attached cannot be deleted — only `dado_de_baja` (test).

## Definition of done

Per CLAUDE.md. Commit: `feat(assets): equipment records with JSONB specs and gated files`.
