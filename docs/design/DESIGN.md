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

## The KPI dashboard (brief 09)

Scene: an administrator on Monday morning, and the same page projected in a demo.
Six numbers legible from across a desk, each followed by the table that says *which
machine* is behind it.

- **No charts, and that is the decision, not a shortcut.** Six single current values
  are a **KPI row of stat tiles**, not six one-bar bar charts; the tables that follow
  carry more than seven meaningful rows, which is a table's job, not a palette's.
  A chart library would also be the first JavaScript dependency on a plant-floor
  phone. (Method: the `dataviz` skill — form first, colour last.)
- **`.vt-kpi-grid` / `.vt-kpi`** — `auto-fit minmax(8.5rem, 1fr)`, no breakpoints: two
  tiles per row at 390px, three at 700px. Marked up as a `<dl>`, so a screen reader
  reads «Disponibilidad → 99,6 %» as the pair it is. Label uppercase muted, value
  1.75rem, one line of context underneath (`2 de 4 a tiempo`) — a percentage with no
  denominator is a number nobody can act on.
- **Proportional figures in the tiles, `tabular-nums` in the tables.** Tabular gives
  every digit the width of a zero, which reads loose at display size; alignment only
  matters where numbers stack in a column.
- **«—» is the empty value**, never 0. An indicator without a denominator (no
  failures, no preventives scheduled, no assets) says it has no data; a 0 would read
  as "perfect" or as "terrible" depending on the indicator, and both are lies.
- **One semantic colour on the whole page**: the backlog tile turns danger red when
  it is not zero. Overdue work is the only number here that is always bad news; if
  four tiles were coloured, none would mean anything.
- **`.vt-bar`** — the ageing bar is a glance-level cue beside a written count, the
  same division of labour as `.vt-progress` on the execution screen. Track and fill
  share a family, severity lives in the fill (amber ≤30 days, danger beyond), and the
  count is always written next to it: the bar never carries a number alone.
- **`.vt-table-wrap`** — money tables are six columns wide and scroll inside
  themselves. The page body still never scrolls sideways; only the nav does.
- The period switcher is a plain GET form that works without JavaScript, enhanced
  with `hx-get` to swap only `#vt-kpi-body` — the selection and the scroll position
  survive the change.

Verified live at 375px and on desktop, both themes: no page-level horizontal
overflow, controls at 50px, contrast on the tiles 5.7:1 (labels) to 17.2:1 (values)
in light and 6.6:1 to 12.4:1 in dark.

## Visual hierarchy pass (brief 11c)

The owner's read after briefs 00–11: the product works, but nothing on five key
screens told the eye where to look first. This pass adds hierarchy and elevation
within the existing tokens — no new colors, no new brand elements, nothing in a
`services.py` or `queries.py` changed anywhere.

- **Equipment detail (`.vt-actions-danger`, `.vt-btn-danger`)** — six actions the
  same shade of navy read as one row. Editar stays Pico's default (the one primary
  action); Hoja de vida / Enviar / Etiqueta QR stay equal-weight secondary reads.
  Dar de baja and Eliminar move to a second row below a border, outlined in danger
  red rather than filled — quiet until interaction, so the row a company looks at
  95% of the time is not sitting next to red. Both still route through their own
  confirm screen; nothing about the confirmation changed.
- **KPI tiles** — `.vt-kpi` gained the same `box-shadow` `.vt-meter`/`.vt-exec-head`
  already use, a touch more padding and grid gap, and `.vt-kpi-value` moved from
  600 to 700 weight with -0.01em tracking: the number pulling rank over its own
  label, not the label going quieter. The six-tile grid, the one-semantic-colour
  rule and the no-charts decision (brief 09) are unchanged.
- **Mobile execution** — already close to the bar brief 05 set; the one real gap
  was the free-text checklist answer and the observación note, the only two
  `<textarea>`s on the screen without the 1rem floor `.vt-report` already uses:
  below 16px, iOS zooms the whole page on focus mid-answer. Fixed for both.
- **Lists** — `asset_list.html`'s filter form moved from Pico's `.grid` (equal
  columns that shrink together, never wrap) to `.vt-filters` (the component
  `work_order_list`/`maintenancerequest_list` already use, built to wrap at
  390px), with a label on every control. `site_list.html` was the one entity list
  in the product still a bare `<ul>`/`<li><a>`; it now uses `.vt-list`/`.vt-row`
  with the address as a subline, like every other list. The equipment detail's
  "Documentos" empty state was a bare `<li>`; it now reads like its neighbours in
  the same file (`.vt-empty`).
- **Login (`.vt-auth`, `.vt-auth-panel`)** — a centred, bordered, elevated panel.
  Not the lazy-card pattern this file otherwise avoids for entity lists: a login
  form is the one thing on the page, so containing it is the content. The error
  message moved from a bare Pico `article.error` to `.vt-alert--error`, matching
  every other message in the product.
- **Global** — button `:active` feedback moved from a 1px nudge to `transform:
  scale(0.97)`: legible as "the interface heard the tap" on a touchscreen, where a
  1px shift reads as nothing. Applies everywhere, including `.vt-seg`'s
  OK/Falla/N-A buttons on the execution screen.

**A pre-existing gap this pass surfaced but did not fix**: most of this file's
`[data-theme="dark"]` component rules (badges, alerts, row tints, the segmented
control's pressed states, field errors) have no `@media (prefers-color-scheme:
dark)` counterpart, and nothing in the app ever sets `data-theme` — so those rules
never fire under real system dark mode, only under a manual toggle this app has
never built. `.vt-req`/`.vt-progress-fill` and the KPI alert/bar colours already
write the rule twice for exactly this reason (brief 05, brief 09); the new
`.vt-btn-danger` above does too. The rest does not — flagged separately for the
owner rather than rewritten wholesale inside a visual-hierarchy brief.

Verified live at 375px and desktop, both themes (`resize_window` plus a
1×1-canvas oklch resolver, since this environment's browser pane does not
composite frames for screenshots): no horizontal overflow on any of the five
screens; every interactive control 48–50px tall; contrast from 4.94:1 (the
pre-existing checklist ordinal chip) to 17.91:1 (the login heading) in light,
5.27:1 to 14.59:1 in dark — every measured pair clears WCAG AA.

## Desktop shell and mobile navigation (brief 11d)

The owner tried the deployed app on both devices. Verdict: mobile — close to right,
two fixes. Desktop — "doesn't feel like a serious program," and it should move toward
Tallaje (`C:\Users\andre\dev\tallaje`), his other product. This pass is interface only:
nothing in `services.py`, `queries.py`, a model or a migration changed for it, and two
things the brief asked for did not ship because they would have required exactly that
(see "What did not ship" below).

**Structure over skin.** Tallaje's own palette is magenta-on-near-black-by-default; its
components are named in Spanish for a shoe warehouse. None of that transfers. What
transfers is *shape*: a fixed sidebar that groups a long nav into named blocks, a page
header that states what the screen is for, a full-width metric strip, dense desktop rows,
a segmented range control. Vectron keeps its own navy/orange tokens, its own light-by-
default/auto-dark strategy (a técnico on a plant floor under sunlight is a different scene
than Tallaje's warehouse clerk, but the reasoning that produced "light by default" is the
same one this file already made in "Theme strategy" — reusing the conclusion isn't
copying, it's the same argument), and its own markup. Nothing is imported from Tallaje's
source; each pattern below was re-derived against Vectron's existing tokens and re-checked
for contrast here, independently.

### Breakpoint

One number, used everywhere in this section: **64rem (1024px)**, matching the breakpoint
Tallaje itself ships for the same sidebar/hamburger split. Below it, phones and small
tablets get the hamburger topbar; at or above it, the sidebar. No third, in-between layout
— a tablet in portrait gets the mobile shell, which is already built for a touch target
that's usually a thumb, not a mouse.

### One shell, two navs, never a parallel page

`base.html` now renders **both** the mobile topbar-with-hamburger and the desktop sidebar
in every response; CSS shows exactly one of them per viewport (`.vt-sidebar` is `display:
none` below the breakpoint, `.vt-topbar` is `display: none` at or above it). This was a
deliberate choice over building two templates or hiding content with JavaScript:

- **Mobile-first stays true.** The mobile markup the owner already approved is untouched
  in substance — same links, same order, same role gating — only its container changed
  from a scrolling row to a dropdown panel. Desktop is additive, not a rewrite.
- **No duplicated permission logic.** Both navs still gate every link with the same
  `{% if user.role == ... %}` conditions already in this file; the conditions are written
  twice (once per nav) because the two navs group items differently (flat list vs. three
  named sections) and a shared include would have had to branch internally on which shape
  to render — more moving parts than two short, readable blocks of the same well-tested
  `{% if %}`s this file already had.
- **Every role-gated link still round-trips through Django's own auth/role check** on the
  view it points to; the nav only decides what's *offered*, exactly as before. Nothing in
  `apps/*/tests/` asserts a link count or an HTML structure for the nav — every existing
  nav-related test checks a URL or a link's visible text is present/absent by role
  (`apps/kpis/tests/test_views.py::PeriodSwitcherTests` and the two `test_the_nav_offers_it_*`
  tests in `apps/kpis` and `apps/audit`), so rendering the same conditional link in two
  places in one response is invisible to them — confirmed by reading every such test before
  touching `base.html`, not assumed.

### Mobile: hamburger + icons only (11d-1)

The nine-to-twelve-link row that used to scroll horizontally is now a `<details>`-free,
JavaScript-free disclosure built from the checkbox hack: a real `<input type="checkbox">`
sized to the full 44px tap box (opacity 0, not `display:none`, so it stays keyboard-
reachable and announces its own checked/unchecked state to a screen reader — the one
accessibility trade-off of this pattern, accepted because the alternative was JavaScript
on a técnico's phone with "mala señal"), a decorative hamburger/× icon beside it, and a
full-viewport `<label>` "scrim" wired to the same checkbox so a tap anywhere outside the
open panel closes it — the exact behaviour the brief asked for, with zero script. The
panel's link set, order and role gating are unchanged from before this brief; only the
container (dropdown instead of scroll-row) and the addition of one icon per item are new.
Equipment detail, the KPI cards, and checklist execution — the three things explicitly
called out as already working — were not touched.

### Icons: one inline SVG sprite, drawn for this brief

`base.html` defines a hidden `<svg><symbol>` sprite once, referenced everywhere with
`<use>`. Reasoning:

- **Sprite over per-use inline paths** (the brief allowed either): a nav icon appears
  twice per response (mobile panel + desktop sidebar); a sprite means each shape is drawn
  once and every occurrence stays in sync by construction, instead of two hand-kept copies
  that can drift.
- **Own paths, not Tallaje's `Icono.jsx`.** The brief was explicit: import the structure,
  not the component. The set below is original geometry at the same visual language
  (24×24 grid, 1.75 stroke, round joins/caps, `currentColor`) so it sits comfortably next
  to Tallaje's without being a copy of it.
- **No icon-font, no CDN library** — the "no external library without an ADR" rule in
  `CLAUDE.md`/this brief made that an easy call: a dozen glyphs don't justify a dependency
  a plant-floor phone would have to fetch.
- Every icon carries `aria-hidden="true"`; the adjacent text already names the action, so
  a screen reader would otherwise hear each link twice.

### Desktop sidebar

Fixed, full-height, `position: sticky`. Top to bottom: the Vectron mark + wordmark (same
lockup as the old top bar), the tenant's company name (`user.company.name` — already in
every authenticated request, no new query), the grouped nav, and the account block pinned
to the bottom via flex (`nav { flex: 1 }` pushes it down, same technique Tallaje uses).

**Grouping.** Eleven flat links is a list, not a structure — the brief named the fix:
*Operación* (Tablero, Mis OTs, OTs, Solicitudes), *Catálogo* (Equipos, Sitios, Planes,
Checklists), *Administración* (Usuarios, Auditoría), each under a small tenue label
(uppercase, muted, the same visual weight as `.vt-kpi dt` already uses elsewhere in this
file — reused, not reinvented). "Contraseña" moves out of the flat list entirely and into
the account block, per the brief.

**Active item.** Solid brand-orange background, near-black text — literally the existing
`--pico-primary-background` / `--pico-primary-inverse` pair this file already validated
for AA and already uses for every primary button. Two reasons this is the CTA pair and not
a softer tint (which is what Tallaje itself actually ships for its own active item, despite
the brief's prose saying "solid"): first, this file's own color strategy already lists "the
active nav indicator" as one of the sanctioned uses of brand orange (see "Theme strategy"
above, unchanged since brief 05) — this is that rule's desktop expression, not a new
exception. Second, reusing an already-AA-checked pair on a single ~2.5rem-tall element
needed no new contrast work, where a new soft-tint pair would have.

**Account block.** A second, independent instance of the same checkbox-hack-plus-scrim
disclosure the mobile menu uses (not `<details>`, so both interactive chrome elements in
this file share one interaction pattern instead of two): avatar (CSS-only initials circle,
computed in the template from `user.first_name`/`last_name`/`get_username` — string
slicing, not a new field), name (`get_short_name|default:get_username`, the same fallback
`home.html` already uses), role (`get_role_display`, likewise already in use), and inside
the disclosure, the "Contraseña" link plus the existing "Salir" form — unchanged endpoint,
unchanged CSRF handling, only relocated.

### Page headers with a subtitle

Every top-level screen reachable from the nav (Tablero, Mis OTs, OTs, Solicitudes, Sitios,
Equipos, Planes, Checklists, Usuarios, Auditoría) now opens on a `.vt-page-head`: title,
one line stating in plain words what the screen is for, and — new — primary actions
aligned to the right of the title instead of dropped in a loose `<p>` below the filters.
Screens that already had a two-line `<hgroup>` (Tablero, OTs, Solicitudes, Planes,
Auditoría, Mis OTs) keep their existing sentence; screens that only had a bare `<h1>`
(Equipos, Sitios, Usuarios, Checklists) gained one. Detail and form screens (equipment
detail, work order detail, create/edit forms) were left as they are — out of the eleven
named screens, and the equipment detail hierarchy specifically is one of the three things
the owner already said not to touch.

### Full-width metric strip

`.vt-kpi-grid` / `.vt-kpi` (brief 09) already are a label/value/context triple in a
`<dl>` — exactly the shape the brief asked for, so this reuses those classes rather than
naming a parallel component. At ≥64rem the grid becomes one bordered flush row with a 1px
divider between cells (a `::before` on every `.vt-kpi` but the first, not a doubled
border) instead of individually shadowed cards; the value gains a system monospace stack
(`ui-monospace, ...` — no webfont: this file's "no webfonts" rule for the plant-floor phone
stays true, since the system stack costs nothing over the network). Below 64rem the
existing two-per-row card grid from brief 09/11c is untouched.

Applied beyond the dashboard **only where a real count already lives in the view's
context** — the brief's own instruction ("si algo parece exigir lógica, repórtalo") ruled
out computing anything new:

- **OTs** (`work_order_list`): `overdue_count` (already powered its old subtitle sentence)
  next to the paginator's total — `page_obj.paginator.count`, a property Django's own
  `ListView` always computes, not a new query.
- **Planes**: `overdue_count`, same reasoning, next to the paginator total.
- **Solicitudes**: `open_count` ("sin revisar", already existed for supervisors/admins)
  next to the paginator total; reporters without `can_review` see only the total, since
  "sin revisar" isn't a number they act on.
- **Equipos, Sitios, Checklists, Usuarios, Auditoría**: each has exactly one number
  available — `page_obj.paginator.count` on the four that paginate (Equipos, Auditoría),
  or `{{ list|length }}` on the two that don't (Sitios, Checklists, Usuarios — the same
  technique `my_work_orders.html` already used for its own `{{ overdue|length }}` before
  this brief, so it isn't new: the view already hands the template the full list to loop
  over, `length` only forces the count Python already has to compute to iterate it). One
  number doesn't make a "row with dividers" — a divider strip around a single tile reads
  as an empty room — so on these five screens the count stays in the header subtitle
  sentence instead (see "What did not ship").

### Dense desktop rows

`.vt-row` / `.vt-row-main` are unchanged in markup and completely unchanged on mobile.
At ≥64rem, `.vt-row-main` switches from two stacked lines (`strong` over `small`) to one
baseline-aligned line, and the leading identifier inside `strong` (an OT's `#123`, an
asset's code, a plan's asset code) gets its own `.vt-row-id` span: muted, monospace, set
off from the name that follows — "identificador destacado, nombre, subtexto" without
re-templating every row from scratch, since the row partials (`_work_order_row.html`,
`_request_row.html`, `_plan_row.html`, `asset_list.html`) already separate "the bold bit"
from "the muted bit"; this only wraps the identifier that was already first inside the
bold bit.

### Segmented period control

The KPI dashboard's period `<select name="periodo">` is now four radio inputs styled as
connected segments, still inside the same `<form>`, still named `periodo`, still firing
the same `hx-trigger="change, submit"` HTMX swap of `#vt-kpi-body` — radios fire `change`
exactly like a `<select>` did, so nothing server-side or HTMX-side changed. The "Sede"
`<select>` is untouched; the brief named only the period control.

### Login, two columns on desktop

A left brand panel (solid navy, the Vectron mark, one line of value proposition, three
checked benefits) appears at ≥64rem beside the existing centered form; below the
breakpoint the page is exactly the form it already was, centered, unchanged. The view,
the form fields, and the CSRF/error handling are untouched — this is a template/CSS-only
addition of a `lg:grid` wrapper around markup that already existed.

### What did not ship (stopped and reported, as instructed)

Two pieces of the brief needed a number this project does not compute anywhere yet, so
they were not built rather than guessed at:

1. **"Pestañas con contador" for OTs-by-state and Solicitudes.** A tab strip with a count
   per state needs a `GROUP BY estado` the views don't run today — `status_choices` in both
   `work_order_list` and `request_list` is a plain list of `(value, label)` pairs for a
   `<select>`, not counts. Adding that aggregation belongs in a services/queries change,
   which this brief explicitly forbids. The existing `<select>`-based state filter is
   untouched.
2. **A single-tile metric strip for Equipos.** The divider-strip component reads as a row
   of at least two numbers; Equipos only has one already-computed count
   (`page_obj.paginator.count`). Rather than inventing a second number (e.g. a status
   breakdown, which is the same missing aggregation as point 1) to fill the row, the one
   real number stays in the page header's subtitle sentence.

Both are one-line additions to a future brief once a status/estado breakdown is worth
adding to the relevant view — flagged here rather than built past the boundary this brief
set.

### Two rendering bugs the earlier briefs' components don't warn about

Neither is specific to this brief's markup — both are Pico CSS styling `<nav>`'s
descendants for its own horizontal-navbar pattern, and would bite the next `<nav>` added
anywhere in this file:

- **`nav ul` fights a vertical list.** Pico flexes any `<ul>` inside a `<nav>` as a
  horizontal row (its own navbar component style), regardless of intervening wrapper
  elements — a descendant selector, not a direct-child one. The mobile dropdown's `<ul>`
  used to sit inside a wrapping `<nav aria-label="…">`; every item rendered in one wide
  horizontal row instead of stacking, invisible in the rendered HTML (server tests
  wouldn't catch it) and only visible by measuring live layout. Fixed by putting the
  `.vt-nav` class directly on the `<ul>` with no `<nav>` wrapper — the same shape the
  original topbar already used, for the same reason. The sidebar's grouped lists **do**
  need to sit inside a real `<nav>` (for the landmark), so there `align-items: stretch`
  is now declared explicitly rather than assumed as the flex default — Pico's rule
  supplies `align-items: center` for that selector and a browser default is only the
  fallback when nothing else claims the property.
- **Pico gives every `<button>` a default bottom margin.** `.vt-logout` and
  `.vt-account-item--btn` are buttons standing in for nav-row `<a>` tags; without an
  explicit `margin: 0` the "Salir" row rendered 16px taller than every link row beside
  it. Both now reset margin alongside the padding/border they already override.

Both were caught the same way: measuring rendered `getBoundingClientRect()` for every
row rather than trusting that a correct-looking CSS rule produced a correct-looking
layout — see [[prueba-el-camino-nuevo]] and the project's own "no-op silencioso" lesson.

### Verified live

`javascript_tool` against the running dev server (`resize_window` plus a canvas-based
`oklch()`/`color-mix()` resolver — this environment's browser pane does not composite
frames for screenshots), at 375px, 390px and 1440px desktop, light and dark, across
Tablero, OTs, Mis OTs, Solicitudes, Equipos, Sitios, Planes, Checklists, Usuarios,
Auditoría and Login:

- **No page-level horizontal overflow** on any of the eleven screens at any width. The
  KPI dashboard's cost table still overflows *inside* its own `.vt-table-wrap` at 390px,
  by design (brief 09) — the page body itself never scrolls sideways.
- **Every measured text/background pair clears WCAG AA**, most by a wide margin: sidebar
  links 17.2:1 light / 12.4:1 dark (default) and 7.0:1 (the solid-orange active state,
  same in both themes — it's the existing primary-button pair); group labels, tenant
  line and account role 5.7:1 light / 6.7:1 dark; the account avatar's initials 5.0:1
  light / 5.7:1 dark; KPI values 17.2:1 light / 12.4:1 dark, KPI labels 5.7:1 / 6.7:1;
  page-header subtitles 5.3:1 light / 7.9:1 dark; the segmented period control 6.7–7.0:1
  in both themes; the login brand panel 12.4–21:1. The one non-obvious measurement was
  `.vt-row-id`: its rule sets `color: var(--vt-muted)`, but the more specific
  `a.vt-row .vt-row-id { color: inherit; opacity: 0.7 }` wins inside a row link, and
  `getComputedStyle().color` reports the pre-opacity value — checked by blending the
  computed color toward the row's own background at the element's *effective* opacity
  (multiplied through its ancestors) rather than reading `color` alone; the real
  on-screen result is 6.2:1.
- **Every mobile menu row is a true 48px tap target** (12 rows, both nav links and
  "Salir"), the panel opens on either the hamburger icon or a tap anywhere else on the
  page (the scrim), and closes the same two ways — confirmed by dispatching the actual
  DOM events a tap produces (`checkbox.click()` / a `change` event on the checkbox),
  not by asserting the CSS rule exists.
- The login page's full-bleed breakout was **first built with the classic
  `left: 50%; margin-left: -50vw` trick** (position:relative on `.vt-auth`) and it
  measured a genuine ~150px horizontal overflow on this Windows machine — that
  construction's math implicitly assumes the vertical scrollbar's width is zero, which
  it was not here. Rebuilt by having `<main>` drop Pico's `max-width`/padding outright
  for this one page (a `vt-auth-main` modifier class, set only when
  `request.resolver_match.url_name == "login"`) instead of fighting the constraint with
  viewport-relative math; re-measured at exactly 0px overflow.

## Assets

`static/img/vectron-mark.svg` is a **provisional** two-tone V drawn from the logo
colors. When the original logo asset exists (SVG or transparent PNG), replace that file
— nothing else needs to change. Favicon = the same file.
