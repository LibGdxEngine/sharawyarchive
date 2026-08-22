# Sha'rawy Archive — Design Reference

## Identity

Two typefaces, one contrast. Amiri Quran for ayah text; IBM Plex Sans Arabic for
all UI chrome. The juxtaposition of the classical Quranic letterform against the
clean geometric Arabic UI face IS the visual identity. Do not flatten this by
using Plex for ayah text or Amiri for navigation labels.

## Restraint

The archive is a reading and listening experience. The interface must get out of
the way. Constraints:

- No card shadows, no gradient heroes, no decorative blobs.
- No cream or terracotta. Those palettes read as "Islamic design cliché".
- One accent colour only. It exists solely for the active-word highlight and
  keyboard focus rings.
- No hero images, illustrations, or stock photos.
- Content column: `min(680px, 100% - 2rem)` centered, with comfortable line
  length for Arabic text (`line-height: 1.8` in reading sections).

## Colour Tokens

All tokens are defined in `globals.css` as CSS custom properties on `:root`.

| Token                | Light          | Dark           | Role                                   |
|----------------------|----------------|----------------|----------------------------------------|
| `--color-bg`         | `#fafaf9`      | `#101312`      | Page ground                            |
| `--color-bg-subtle`  | `#f4f4f2`      | `#181b19`      | Slightly recessed surfaces             |
| `--color-surface`    | `#ffffff`      | `#1e2220`      | Cards, modals, inline surfaces         |
| `--color-ink`        | `#141412`      | `#f0ede8`      | Primary text                           |
| `--color-ink-muted`  | `#5c5b57`      | `#a8a49d`      | Secondary text, meta                   |
| `--color-ink-faint`  | `#9b9994`      | `#6a675f`      | Placeholder, disabled text             |
| `--color-border`     | `#e4e3de`      | `#2c302d`      | Standard borders                       |
| `--color-border-subtle` | `#eeede8`  | `#242724`      | Subtle dividers                        |
| `--color-accent`     | `#1a6b4a`      | `#3aad7a`      | Active-word highlight + focus rings    |
| `--color-accent-bg`  | `#d4eee3`      | `#0d2e1f`      | Highlight background behind active word|

The accent is a deep forest green (light) / cool mint-green (dark). It reads as
calm authority. Never use it for decorative purposes.

## Type Scale

All sizes in `rem` (base 16px).

| Step | Size   | Weight | Font       | Usage                           |
|------|--------|--------|------------|---------------------------------|
| xs   | 0.75rem | 400   | Plex Arabic | Labels, timestamps, meta       |
| sm   | 0.875rem| 400   | Plex Arabic | Secondary body, captions       |
| base | 1rem    | 400   | Plex Arabic | Body, search inputs, buttons   |
| md   | 1.125rem| 500   | Plex Arabic | Section headings, nav items    |
| lg   | 1.5rem  | 600   | Plex Arabic | Page titles                    |
| ayah | 1.5rem  | 400   | Amiri Quran | Ayah text display              |
| ayah-lg | 2rem | 400  | Amiri Quran | Featured ayah display          |

`line-height` for Amiri Quran text: 2.2 (generous — Arabic fully vocalised text
needs room for harakat above and below the baseline).

## Active-Word Highlight (the Signature Element)

When audio is playing and the transcript is visible, exactly one word is
"active" — the word currently being spoken. Styling:

```css
.word-active {
  background-color: var(--color-accent-bg);
  color: var(--color-accent);
  border-radius: 2px;
  padding: 0 2px;
  /* transition OFF when prefers-reduced-motion: reduce */
  transition: background-color 80ms ease-out, color 80ms ease-out;
}
```

The highlight loop is driven by `requestAnimationFrame` with a binary search
over the word array. It bails early if the active index has not changed since
the last frame (compare `currentTime * 1000` against `word.e`).

Under `prefers-reduced-motion: reduce`, the transition is instant (transition
duration is zeroed by the global media-query rule in globals.css).

## Layout Zones

```
┌─────────────────────────────────────────────────────────┐
│  Global header: site name (Plex Arabic SemiBold) + search│
├─────────────────────────────────────────────────────────┤
│                                                         │
│          Reading column (max 680px, centered)           │
│                                                         │
│    Ayah text (Amiri Quran, 1.5rem, lh 2.2)             │
│    ─────────────────────────────────────────            │
│    Transcript words (Plex Arabic, 1rem, lh 1.8)        │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Audio player bar: fixed bottom, full width             │
│  title · progress · position/duration · rate · sleep    │
└─────────────────────────────────────────────────────────┘
```

The audio player bar ("the gilded transport", `.player-bar` in globals.css)
is always visible once a track is loaded. It uses `position: fixed; bottom: 0`
with a `backdrop-filter: blur(10px)` over the page content below, capped by a
gold hairline and a seek ribbon that rides its top edge. The bar's height is
not fixed: `PlayerBar.tsx` measures itself and writes the exact pixel value
into `--player-bar-height` on `<html>`, so `.page-shell` always reserves
precisely the bar's real height (the stylesheet `--player-bar-height` values
are just the fallback before any track loads).

## Quality Floor

These are non-negotiable baselines, enforced at the CSS level:

1. **Focus visible**: every interactive element gets `outline: 2px solid
   var(--color-accent); outline-offset: 2px` on `:focus-visible`. This is set
   globally in globals.css — individual components must not override it with
   `outline: none` unless they provide an equivalent custom indicator.

2. **Reduced motion**: the `@media (prefers-reduced-motion: reduce)` block in
   globals.css zeros all transition and animation durations and disables
   `scroll-behavior: smooth`. Any new component that adds motion must add a
   corresponding reduced-motion override. The active-word highlight must be
   instant (no colour fade). Auto-scroll of the active transcript line must not
   animate.

3. **Minimum viewport**: the layout must be fully functional at 360px wide.
   No horizontal scroll on `<body>`. Wide content (waveform, word arrays) must
   use `overflow-x: auto` on a wrapper.

4. **RTL-first**: `dir="rtl"` is on `<html>`. Never use `margin-left` or
   `padding-left` for layout spacing that should mirror in RTL — use logical
   properties (`margin-inline-start`, `padding-inline-end`, etc.) or Tailwind
   RTL-aware utilities.

## Landing page — brand exception

The landing page (`src/app/page.tsx`) implements the approved Claude Design
mockup ("Sharawy Archive Landing") and is a deliberate, **scoped** exception to
the Restraint rules above. On this one route only:

- A gold brand palette (`--landing-*` tokens in `globals.css`, with dark-mode
  variants) is used decoratively: waveform motif, search hero, chips.
- The search box carries a soft shadow and a gold `:focus-within` ring
  (`.landing-search`).
- Two brand faces are added, loaded only on this route via `next/font/local`:
  Reem Kufi (`--font-brand`, site title) and Amiri text (`--font-amiri`,
  tagline + Quranic glyph accents).
- Keyboard focus rings remain visible but take the brand gold
  (`.landing :focus-visible`).

Everything else in this document still governs every other page. Do not let
the gold palette or the shadow leak past `.landing`, and do not "fix" the
landing back to the green token system.

## Surah page — mushaf illumination exception

The surah reading page (`/surah/[n]`) is a third brand exception, joining the
landing, the surah index and the verse player. Scope: `.surah-page` tokens in
`globals.css`, applied by `src/app/surah/[n]/page.tsx`. On this route:

- The gold manuscript palette (`--sp-*` tokens, dark-mode variants included)
  is used decoratively: an illuminated-opening hero panel (star lattice
  bands, corner flourishes, hairline inner frame, radial halo), an
  eight-point-star divider, and badges for revelation place / ayah count.
- Every ayah carries a rosette verse seal (`.ayah-seal`) — concentric rings,
  a dotted outer ring that rotates a quarter-turn on hover, Arabic-Indic
  numerals. The `?ayah=` active verse keeps the seal solid gold.
- Segment affordances are gilded chips (`.sp-chip`); pagination and the
  prev/next surah cards lift with a gold glow on hover.
- Quran text colours itself in sepia manuscript ink (`--sp-quran-ink`); the
  Amiri Quran face and 2.2 line-height rules are unchanged.
- All motion (staggered ayah entrance, seal rotation, chip lifts) is gated
  by `prefers-reduced-motion: no-preference`, per the Quality Floor.

The bar styling (`.player-bar`, `.player-seek`, `.player-play`, `.player-eq`,
`.player-chip`) applies globally to the fixed transport on every route.

## Search page — illuminated results exception

The search results page (`/search`) extends the manuscript language. Scope:
`.search-page` / `--srch-*` tokens in `globals.css`, applied by
`src/app/(site)/search/page.tsx`. On this route:

- Verse hits are whole-card links (`.search-hit`) with rosette seals
  (`.ayah-seal`, reused via `--sp-*` aliases inside the scope) — the
  parchment card materialises on hover/focus, the meta line turns gold and
  a chevron slides forward (negative X: RTL).
- The eight-point-star divider separates the mushaf zone from the
  machine-transcript zone, which deliberately stays on neutral surfaces
  with the green accent chip (Rule 1: gold marks authentic Quran only).
- All motion (hero rise, hairline draw, staggered card entrance, chunk-row
  entrance) is gated by `prefers-reduced-motion: no-preference`.

## File Checklist

- `src/fonts/AmiriQuran-Regular.ttf` — self-hosted
- `src/fonts/IBMPlexSansArabic-Regular.ttf` — self-hosted
- `src/fonts/IBMPlexSansArabic-Medium.ttf` — self-hosted
- `src/fonts/IBMPlexSansArabic-SemiBold.ttf` — self-hosted
- `src/fonts/ReemKufi-Variable.ttf` — self-hosted (landing only)
- `src/fonts/Amiri-Regular.ttf` — self-hosted (landing only)
- `src/fonts/index.ts` — `next/font/local` definitions
- `src/app/globals.css` — all tokens and base styles
- `src/app/layout.tsx` — `<html dir="rtl" lang="ar">`, font variables on `<html>`
