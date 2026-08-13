# PRODUCT.md

**Product:** Vectron Management — multi-tenant CMMS SaaS for Spanish-speaking SMBs that
own machinery: equipment records ("hojas de vida"), preventive maintenance plans, work
orders with checklist + photo evidence, audit-ready reports (ISO 9001, SG-SST,
INVIMA/GMP). Monthly subscription per company. Pilot niche: Flowpac packaging machines;
data model machine-agnostic.

**Register:** product — design serves the tool. Clarity, speed and trust over spectacle.

**Users & scenes:**
- Técnico: phone at 390px on a plant floor, bright light, gloves, weak network. Scans a
  QR on the machine, executes a checklist, uploads photos. Big targets, zero ambiguity.
- Supervisor: desktop/tablet; plans, assigns, verifies, watches KPIs.
- Administrador: desktop; users, sites, subscription.
- The app is evidence for auditors: states must read unambiguously (a `verificada` badge
  is a seal, not a decoration).

**Brand:** Vectron Ingeniería — navy `#1E2A38`, industrial orange `#F28619`, silver-gray
type. Tagline: "Cuidamos tu maquinaria, impulsamos tu producción". See
`docs/design/DESIGN.md` for the visual system; `static/css/vectron.css` implements it.

**Stack constraint:** Django templates + HTMX + Pico CSS v2 (vendored, no build step).
Theme = CSS variables over Pico. UI text es-CO; code and docs English.
