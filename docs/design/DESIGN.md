# DESIGN.md — Vectron Management visual system

The app is branded **Vectron Management** (brand: Vectron Ingeniería — navy + industrial
orange, from the owner's logo). Repo slug stays `cmms-saas`. This file is the source of
truth for UI decisions; `static/css/vectron.css` implements it over Pico CSS v2.

## Theme strategy

Scene: a technician on a plant floor under bright ambient light, phone in hand, often
gloves on; supervisors and admins on desktop. Therefore: **light content by default**
(sunlight legibility), **automatic dark mode** via `prefers-color-scheme` (and
`[data-theme]` override), and the **top bar always brand navy in both themes** — the
brand chrome is constant, the content adapts.

Color strategy: restrained. Tinted cool neutrals + navy chrome; **orange ≤10% of any
screen**, reserved for: primary action buttons, links, focus rings, the active nav
indicator, and the `en_proceso` state. If everything is orange, nothing is.

## Tokens (all pairs validated WCAG 2.1 AA — script in the reviewer's log)

| Token | Hex | OKLCH | Use |
|---|---|---|---|
| `--vt-navy-800` | `#1E2A38` | `oklch(0.281 0.031 253)` | **Brand navy** (logo bg): top bar, `verificada` badge |
| `--vt-navy-900` | `#131C26` | `oklch(0.223 0.024 251)` | Dark-theme bg; body text on light |
| `--vt-navy-950` | `#10181F` | `oklch(0.204 0.018 245)` | Ink on orange buttons; h1 on light |
| `--vt-navy-700/600` | `#2B3B4E` `#3C5064` | — | Dark surfaces / dark borders |
| `--vt-slate-500` | `#57697B` | — | Muted text on light (5.3:1 on bg) |
| `--vt-slate-300/200/100` | `#C3CDD7` `#DEE5EB` `#ECF0F4` | — | Borders / subtle fills on light |
| `--vt-bg-light` | `#F6F8FA` | `oklch(0.978 0.003 248)` | App background, light |
| `--vt-ink-on-dark` | `#E8EDF2` | — | Text on navy (12.3:1) |
| `--vt-muted-on-dark` | `#A2B2C2` | — | Muted on navy (6.7:1) |
| `--vt-orange-500` | `#F28619` | `oklch(0.724 0.168 57)` | **Brand orange** (logo V): primary buttons (with `navy-950` text — white text on this orange fails AA), active nav underline |
| `--vt-orange-600` | `#D96D0F` | — | Hover/pressed |
| `--vt-orange-700` | `#AC5407` | — | Link color on light (5.2:1 on white) |
| `--vt-orange-300` | `#F4A75B` | — | Links/accents on dark (8.6:1) |
| `--vt-orange-100` | `#FDEFE1` | — | Orange tint bg (badges) |
| success / warning / danger / info | `#1D6E3F` `#755808` `#AC322C` `#2A628F` (+`-300` dark, `-100` tint) | — | Semantic states; **warning is amber-gold, never the brand orange** |

## Work-order states → `.vt-badge--*`

`abierta` slate · `asignada` info blue · `en-proceso` brand orange · `hecha` success ·
`verificada` solid navy pill with orange ✓ (sealed evidence) · `vencida` danger ·
`critica` warning · `cancelada` outline + strikethrough.

## Maintenance-plan states → `.vt-badge--*` (brief 04)

`vencido` danger · `por_vencer` warning amber (a calendar plan due within 7 days, or a
meter plan past 90% of its interval) · `al_dia` quiet slate — the healthy majority of a
list must stay silent · `sin_lecturas` info (a meter plan on a machine nobody has read
yet) · `inactivo` outline + strikethrough.

An overdue row also takes `.vt-row--vencido`: a 6% danger tint across the **whole** row,
never a coloured left border. The tint guides the eye down a long list; the badge, not
the colour, carries the meaning.

## Work-order execution — the phone screen (brief 05)

Scene, restated because every decision below falls out of it: a technician on a
plant floor, bright ambient light, **one hand free**, gloves on, network that comes
and goes. This is the screen the product is judged on.

- **Two tap sizes.** `--vt-tap` = 44px is the accessibility floor used across the app;
  `--vt-tap-lg` = 48px is the plant-floor size, used by every control on the execution
  screen. A gloved thumb is not a mouse pointer.
- **`.vt-exec-head`** — machine context (code + name + state) pinned under the top bar
  (`top: 3.5rem`). Mid-checklist, "which machine am I on?" must never cost a scroll.
- **`.vt-progress`** — a 6px track plus a sentence. Deliberately *not* the hero-metric
  template: the number that matters ("faltan 2 obligatorios") is written in words; the
  bar is a glance-level cue only. Updated by an HTMX out-of-band swap on every item
  save, so the counter and the rows are always one response apart, never two.
- **`.vt-check-item`** — one item, one `<form>`, one round trip. Saved per item because a
  dropped connection must cost the last tap, not the last twenty minutes. Answered items
  recede (muted text); `is-falla` takes a 6% danger tint across the whole row so a
  supervisor can find failures while scrolling — a tint, never a coloured side border.
  `.htmx-settling` flashes the row green for 400ms: long enough to register while
  looking at your hands, short enough not to queue behind fast taps.
- **`.vt-check-order`** — the ordinal as a quiet chip, so every item's text starts at the
  same left edge instead of being indented by "10." vs "1.".
- **`.vt-num`** — numeric answer: a 48px `inputmode="decimal"` field with the unit beside
  it and the expected range as hint text underneath. Out-of-range is stated as a verdict
  ("queda registrado como falla"), never left for the reader to infer from a colour.
- **`.vt-check-note`** — the observación collapsed inside `<details>`, submitted by the
  same button that saves the answer (one round trip). The summary says so.
- **`.vt-photo-grid`** — square thumbnails, `auto-fill minmax(5.5rem, 1fr)`, no
  breakpoints. The upload input carries `capture="environment"`, so evidence is one tap
  from the rear camera instead of a trip through the gallery.
- **`.vt-submit-lg`** — one full-width primary action per screen ("Terminar OT").

## Work-order detail (brief 05)

- **`.vt-seal`** — solid navy banner with an orange ✓, matching the `verificada` badge:
  a sealed work order says so once, at the top, in words ("Ya no se puede modificar").
- **`.vt-timeline`** — who/when as a plain bordered list, oldest first. No decorative
  vertical rail: the information is the name and the timestamp. Brief 08 replaces the
  derived events with real audit rows; the component does not change.
- **`.vt-filters`** — filter bars wrap (`flex-wrap`) rather than squeezing five controls
  onto one phone line; each control gets `flex: 1 1 10rem`.
- **The top bar scrolls, it does not wrap.** With «Mis OTs» and «OTs» added, the nav no
  longer fits a 390px row. Wrapping would make the bar two or three rows tall depending
  on role and viewport — and the execution screen's sticky machine bar has to sit at a
  known offset beneath it (`top: 3.5rem`). So `.vt-nav` scrolls horizontally inside
  itself, with the scrollbar hidden (it would eat a third of a 3.5rem tap target). The
  page body never scrolls sideways; only the nav does.

## The QR scan — the machine's own screen (brief 06)

Scene: a sticker on a machine, a phone held in front of it. Everything below falls out
of the fact that **the app does not know who is holding the phone until it does**.

- **`.vt-plate`** — what a scan shows with no session, and to anyone outside the
  machine's company (identical plate either way — same template, same two values, nothing
  that varies with the machine's owner — so a login can never reveal whose machine a UUID
  is; the surrounding top bar does differ, because that is about the viewer, not about the
  machine). It shows the internal code and the name: exactly what is already printed on
  the label the person is standing in front of. The screen's job is to say almost
  nothing, and that has to read as deliberate rather than broken — so it borrows the
  object it stands in for: the engraved nameplate riveted to the machine's frame. A
  bordered plate, an inner rim (`outline-offset: -6px`, no second element), the code cut
  into it in `tabular-nums` at `clamp(2rem, 11vw, 3rem)`, the name beneath. One sentence
  says what a session would add; one button starts one. **No badge, no company, no
  status, no history, and no link carrying the asset's pk** — the template is not even
  handed the asset object.
- **`.vt-scan-id`** — the live view's identity block, deliberately the same
  «CÓDIGO — Nombre» lockup as the execution screen's sticky bar: a technician who scans
  and then executes should recognise the machine, not re-read it.
- **`.vt-row--go` + `.vt-go`** — the technician's row goes *straight* to the execution
  screen, because that is why they scanned. One 48px target for the whole row beats a row
  plus a fingernail-sized button; the orange chip is the affordance, not the tap target.
  This is the screen's one primary action, which is what buys it the orange.
- Role sections are chosen by **`audience`** (resolved once in
  `apps/assets/services.scan_audience`), never by `user.role` in the template. Two copies
  of "who may see this machine" is two chances to get tenant isolation wrong.

## The printable label (brief 06)

- **`.vt-label`** — a physical object, so it is sized in **millimetres**: 70 × 40 mm
  (stock adhesive label) with a 30 mm QR, scannable at roughly arm's length. Black on
  white **in both themes, on screen too**: this is a preview of ink, and a dark-mode
  preview is a picture of something the printer will never produce.
- The QR is **inline SVG** rendered server-side by `segno` (`apps/assets/qr.py`): no image
  file to store, no `/media/` URL to gate, no JavaScript, and vector output that stays
  sharp at any sticker size. Error level M (~15% recoverable) because the sticker lives in
  grease and steam; quiet zone 2 modules.
- `.vt-label-url` prints the URL in 2.4 mm type — the typed fallback for a label too dirty
  to scan.
- **`.vt-noprint`** on everything that is app chrome; `@media print` also drops the top bar
  and the container's max-width. No print button: this brief ships without JavaScript, and
  what the operator needs before pressing Ctrl+P is the paper settings (100% scale, no
  headers), which the page states.

## Failure reports and the audit log (brief 08)

Scene for the report: the same plant floor as the execution screen, but the person
holding the phone may never have opened this app before — a machine operator, someone
from the office walking past. Every decision below is about not losing them.

- **`.vt-report`** — two fields and one full-width button, nothing else. The machine is
  named at the top in the `.vt-scan-id` lockup, so «which one am I reporting?» is never a
  question. The textarea is `1rem`: below 16px iOS zooms the page on focus, and a viewport
  that jumps mid-sentence is how a half-written report gets abandoned. The photo input is
  `capture="environment"` at the 48px plant-floor size.
- **Request state badges** — no new colours: `nueva` amber (the "necesita a alguien
  pronto" already used by `por_vencer`), `convertida` success, `rechazada` the quiet
  strikethrough of `cancelada`/`inactiva`. Amber and never the brand orange, which means
  «en proceso» everywhere else in the product.
- **`.vt-row--pendiente`** — an undecided report takes a 6% amber whole-row tint, the same
  device as `.vt-row--vencido` in danger: it guides the eye down a supervisor's queue while
  the badge, not the colour, carries the meaning.
- **`.vt-decision`** — the supervisor's panel is a bordered block, not page furniture:
  converting opens a work order and rejecting closes the door on somebody's report. One
  primary action («Convertir en OT correctiva», full width), rejection as a quiet outline
  button leading to its own screen, because it costs a written reason.
- **Two buttons, two acts.** The equipment record offers «Reportar falla» (primary — the
  solicitud, open to every role) *and* «Abrir OT correctiva» (secondary — the work order,
  supervisors and technicians). The wording carries the difference; the roles are decided
  in the service layer, never in the template.
- **`.vt-audit`** — the log is a list of blocks, **not a table**. Six columns of
  action/model/id/person/timestamp at 390px is a horizontal scrollbar with data in it, and
  the page body must never scroll sideways (only the nav does). Each entry: what happened
  (action badge + object) on line one, who and when in muted meta, then the changed fields
  as «campo: de → a». `.vt-audit-arrow` carries the direction — the old and new values are
  the same kind of thing and look the same, because colouring one red and one green would
  claim a judgement the log does not make.
- **Audit action badges are the quietest in the product** (slate for create/update, info
  for transition/send). Only `Eliminación` takes a semantic colour: it is the one an
  auditor scans a page looking for.
- **`.vt-field-inline`** — a labelled control inside a filter bar (the date range), label
  above input, flexing like every other `.vt-filters` child.

Verified live at 390px: no horizontal overflow on the report form, the queue, the request
detail, the scan screen or the audit log; every control ≥48px; dark-mode contrast measured
at 5.3:1 (badges) to 14.6:1 (field names).

## Component rules

- **Top bar** (`.vt-topbar`): navy in both themes, sticky, brand lockup left (mark +
  VECTRON / MANAGEMENT mirroring the logo hierarchy), nav right, active link = white +
  2px orange underline flush with the bar edge. "Salir" is a quiet outline button.
- **Entity lists** (equipos, OTs): `.vt-list` + `.vt-row` rows — never grids of
  identical cards. Row = name + muted meta left, state badge right, ≥44px tap target,
  whole row is the link.
- **Checklist execution**: `.vt-check-item` + `.vt-seg` segmented OK/Falla/N-A buttons,
  ≥44px, `aria-pressed` state, color-coded when selected.
- **Alerts / Django messages**: `.vt-alert .vt-alert--{success,warning,error,info}` —
  tinted bg + full 1px border. **Never a thick colored left-border stripe.**
- **Forms**: Pico defaults themed via vars; focus ring 2px orange offset 2px; labels
  always visible (no placeholder-as-label).
- **Buttons**: primary = orange bg + near-black navy text; secondary = navy. One
  primary action per screen.
- Headings use `text-wrap: balance`; body text ≤72ch (`main.container`); wide tables
  opt into `main.container--wide`.
- **Action rows** (`.vt-actions`): flex + wrap, and one button per line below 26rem —
  Pico's `<a role="button">` is inline-block with no wrapping contract, so a bare `<p>`
  of buttons overflows a 390px viewport.
- **Empty states** (`.vt-empty`): dashed border, what is missing in ink + what to do
  about it in muted + at most one button. An empty list is a starting point, not an
  error, so it never uses a semantic colour.
- **Forms**: group mutually exclusive sections in `.vt-fieldset` (Pico v2 strips
  fieldset borders); render fields through `templates/maintenance/_field.html`, which
  ties help text and errors to the input with `aria-describedby` and marks invalid
  inputs `aria-invalid` — `{{ form.as_p }}` does neither.
- **Hour meter** (`.vt-meter`): the reading is the headline, in `tabular-nums`; one
  number input (`inputmode="decimal"`) and one full-width ≥44px button under it.
- Motion: 150ms ease-out transitions on interactive elements only; full
  `prefers-reduced-motion` fallback. No entrance animations on CRUD screens.
- Z-index: use the `--vt-z-*` scale, never arbitrary numbers.

## Typography

System font stack (Pico default) — no webfonts: plant-floor phones on weak networks
must not wait for type. Brand voice comes from the lockup (uppercase, tracked) and
color, not from a display font. UI text Spanish (es-CO); sentence case; concise labels.

## Charts (brief 09)

Build KPI charts from these tokens (navy/slate structure, orange only to highlight the
one series that matters, semantic colors for states). Read the `dataviz` skill before
writing chart code.

## Assets

`static/img/vectron-mark.svg` is a **provisional** two-tone V drawn from the logo
colors. When the original logo asset exists (SVG or transparent PNG), replace that file
— nothing else needs to change. Favicon = the same file.
