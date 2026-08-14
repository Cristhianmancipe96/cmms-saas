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
