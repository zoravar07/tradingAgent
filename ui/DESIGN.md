# Z Money — Design System

One coherent product, not eight screens. Every rule here is enforced by a token in
`src/index.css` or a component in `src/components/ui/`. If a screen needs a value
that isn't on a scale below, the scale is wrong — fix the scale, not the screen.

This build is a rewrite of the previous dark system, built to a reference design:
white ground, card-based, generously spaced, with a large confident type scale.
The sizes below are measured off that reference, not invented.

---

## 1. Color

Light-only by design. There is no dark mode and no theme toggle — a half-converted
palette is worse than either.

### Surfaces

Depth comes from hairlines plus one barely-there shadow, not from a stack of grays:
on white, a four-step surface ladder collapses visually and stops carrying meaning.

| Token | Value | Use |
|---|---|---|
| `--canvas` | `#ffffff` | App ground. The main content column. |
| `--rail` | `#f7f7f8` | Sidebar. The only tinted region of chrome. |
| `--surface` | `#ffffff` | Cards. |
| `--inset` | `#fafafa` | Card footers, table headers, muted rows. |
| `--inset-strong` | `#f2f2f4` | Hover on an inset, meter tracks, count chips. |

### Borders

Hairlines only — `1px`, never `2px`, never a shadow standing in for a border.

| Token | Value | Use |
|---|---|---|
| `--line` | `#e9e9ec` | Default hairline. Every card, every divider. |
| `--line-strong` | `#d7d7dd` | Interactive borders (buttons, inputs). |

### Elevation

One shadow: `--shadow-card: 0 1px 2px rgba(17,17,20,.04)`. On white a card is
defined by its hairline; the shadow only stops it floating. No second elevation
step, no hover lift on non-clickable cards.

### Ink

| Token | Value | Use |
|---|---|---|
| `--ink` | `#111114` | Primary text, values, headings. |
| `--ink-dim` | `#5b5b66` | Body copy, secondary values. |
| `--ink-faint` | `#8e8e99` | Labels, captions, units, metadata. |

Three levels, no more. If something needs a fourth, it's a size or weight problem,
not a color problem.

### Accent — one hue, used sparingly

`--accent: #4f5bd5`. Reserved for: the active nav item, focus rings, primary
buttons, section glyphs, and links. **Not** decoration.

- `--accent-wash: #eef1fe` — the reference's soft callout ground.
- `--accent-line: #dde3fc` — accent-tinted hairline.

### Semantic colors — reserved, never decorative

Status colors are reserved and never reused as a "series color".

| Token | Value | Means exactly |
|---|---|---|
| `--gain` | `#16a34a` | A BUY action; an unrealized gain; high conviction. |
| `--loss` | `#e5484d` | A SELL action; an unrealized loss; a score below the floor. |
| `--risk` | `#c2710c` | A genuine alert, or a mid-band conviction score. |

Each has a `-wash` variant for chip and callout backgrounds.

### Conviction — banded, and the words agree with the color

Conviction gets three bands, and the label always matches the color. The reference
reads the score out loud ("High conviction") beside a green bar; a single neutral
ramp would leave the words contradicting the bar.

| Range | Label | Color |
|---|---|---|
| `< 40` | Below conviction floor | `--loss` |
| `40–64` | Moderate conviction | `--risk` |
| `≥ 65` | High conviction | `--gain` |

40 is `config.yaml`'s `risk.min_hold_conviction` — the point where the score stops
being a measurement and becomes an instruction. Track is `--conviction-track`
(`#ebebee`). **Flat fill, no gradient**: a gradient along a bar whose only variable
is length misstates the value.

---

## 2. Typography

One family. **Inter** — a neutral grotesque, matching the reference. The previous
build used three families (Space Grotesk / JetBrains Mono / Fraunces); the
reference sets everything, numbers included, in one sans, and mixing a display
face into it fought the layout rather than helping it.

### Scale

Eight steps. Anything outside this list is a mistake.

| Class | Size / line-height | Weight | Use |
|---|---|---|---|
| `.t-hero` | 34px / 1.15, `-0.025em` | 700 | Screen title. One per screen. |
| `.t-figure` | 40px / 1, `-0.03em` | 700 | The conviction score. |
| `.t-display` | 29px / 1.1, `-0.025em` | 700 | Ticker on a feature card. |
| `.t-stat` | 22px / 1.2, `-0.02em` | 700 | Stat-row values. |
| `.t-lead` | 17px / 1.5 | 400 | Screen subtitle, the "why" sentence, callouts. |
| `.t-title` | 16px / 1.4, `-0.01em` | 600 | Section and card headings. |
| `.t-body` | 15px / 1.6 | 400 | Running prose, table cells, nav. |
| `.t-meta` | 13px / 1.45 | 400 | Stat labels, captions, chips. |

`.t-pill` (12.5px, `0.04em`, uppercase, 600) is the one uppercase step, and belongs
to `StatusPill` only. Stat labels in the reference are Title Case at `.t-meta`, not
uppercase eyebrows.

### The figure rule

`.num-table` applies `tabular-nums` and is used **only in columns** — tables, stacked
rows, axis ticks — where digits must align vertically. A large standalone value with
tabular figures reads loose, because every digit gets the width of a `0`. `.t-hero`,
`.t-figure`, `.t-display` and `.t-stat` deliberately omit it.

---

## 3. Spacing & grid

One 4px-based scale, running one step roomier than the previous dark build because
the reference is a generously spaced layout, not a trading terminal.

| Token | Value | Typical use |
|---|---|---|
| `--sp-1` | 4px | Icon-to-label gap. |
| `--sp-2` | 8px | Within a row; chip padding. |
| `--sp-3` | 12px | Between stacked fields; nav item padding. |
| `--sp-4` | 16px | Between card sections. |
| `--sp-5` | 24px | Card block padding; between cards. |
| `--sp-6` | 32px | Card inline padding; between screen sections. |
| `--sp-7` | 40px | Screen gutter and top padding. |
| `--sp-8` | 56px | Empty-state block padding. |

### Radii — concentric, never uniform

| Token | Value | Use |
|---|---|---|
| `--r-chip` | 6px | Pills, badges, tags. |
| `--r-inner` | 8px | Elements nested inside a card; buttons; inputs. |
| `--r-card` | 12px | Cards, panels. |

### Screen frame

Every screen uses the same frame — this is what makes eight screens read as one
product:

```
ScreenShell
  ├─ header    title (.t-hero) + subtitle, date + actions right-aligned
  └─ content   max-width 1180px, --sp-7 gutter, --sp-6 between sections
```

The header scrolls with the page. At 34px a pinned header eats a third of a laptop
viewport.

---

## 4. Component patterns

The card is built **once**, in `src/components/ui/Card.tsx`. Trade, Position,
Watchlist, Order, Insight and Journal entries are compositions of it.

### `Card` — the one container

```tsx
<Card tone="neutral | buy | sell | accent | risk" interactive={false}>
  <CardHeader />              // mark + ticker + trailing control
  <CardBody />                // the screen-specific middle
  <CardFooter inset />        // full-bleed tinted strip
</Card>
```

`tone` paints a **full-height 3px stripe down the left edge** — the reference's
strongest card signal, and the only place semantic color touches the card. A washed
background would make the color decorative and swamp the hairline the card is
defined by.

`interactive` is opt-in and off by default: a hover lift on a non-clickable card
promises an affordance that doesn't exist.

### `StatRow` — structured numbers

The reference's labelled columns separated by hairline rules, label above value,
collapsing 4 → 2 columns on narrow viewports.

This is the fix for the run-on line the previous build used:
`1 sh · LIMIT $478.53 · ~$479 · 13.8% of NAV`. Scanning a column of labels is what
makes numbers readable. Units are spelled out — `1 share`, never `1 sh`.

### `ConvictionScore` / `ConvictionBar`

`ConvictionScore` is the full reference module: heading with an info affordance, the
score as `.t-figure` against `/ 100`, a bar, and the band in words. The figure, the
bar and the label are **one widget** — no screen restates the score beside it.

`ConvictionBar` is the same thing without the heading, for lists, where the full
module twenty times over stops being a focal point. Same bands, same colors.

### `Disclosure` — "View full rationale & details"

A full-width control across the bottom of a card that expands long-form content in
place, on `grid-template-rows: 0fr → 1fr`. The previous build put long prose behind
a right-side `Sheet`; the reference opens it where it sits, which keeps it out of
the scannable list without moving the reader elsewhere. `Sheet` remains for
genuinely long multi-section analysis.

### `Callout` — the soft highlighted box

Tinted panel, icon, bold line, supporting line, optional outlined action. For things
that are advice rather than data — a process reminder, a drift warning. Keeping
those in a tinted box stops them being read as another figure.

### `TickerMark`

The square mark opening a card. The reference shows a company logo; there is no logo
source in this app, so this is a monogram tile at the same size and radius. It's a
placeholder for a *logo*, not for data — the letters are the real ticker.

### `LineChart`

Inline SVG, no chart library. One series with a handful of points doesn't justify a
dependency, and an SVG we own is the only way to keep the axis on the same tokens as
everything else. Non-zero y-axis (NAV moves within a narrow band; forcing zero
flattens it), stated in the caption. Dots are drawn as well as the line, because
between four readings the line is interpolation. X is spaced by elapsed time, and
labels are thinned when points bunch.

### Jargon policy

Every domain term gets a plain-English gloss on first appearance, via `Term`.
Glosses live in one map (`src/lib/glossary.ts`). Gloss the **label**, never a word
inside prose that already sits under a heading of the same name.

---

## 5. Motion

Three curves, no others:

```css
--ease-out:    cubic-bezier(0.23, 1, 0.32, 1);
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
```

Durations: press 120ms · hover 160ms · expand 220ms · meter 280ms · sheet 300ms.
**Nothing over 300ms.**

| Element | Motion | Purpose |
|---|---|---|
| Pressable controls | `scale(0.98)`, 120ms | Feedback |
| Disclosure | `grid-template-rows: 0fr → 1fr`, 220ms | Preventing a jarring change |
| Conviction meter | width, 280ms, on mount | State indication |
| Card list entrance | 8px rise + fade, 220ms, 40ms stagger | Preventing a jarring change |

### What deliberately does *not* animate

- **Numbers do not count up.** These are figures you read to make a decision, and a
  count-up means the first stretch after load displays incorrect values.
- **Sidebar navigation.** Used constantly; animation makes frequent actions feel slow.
- **Non-clickable cards.** No hover lift, no glow.

The one exception is the sidebar's market countdown, which ticks every second —
it is a countdown, so a static value would be wrong a second later.

### Reduced motion

`prefers-reduced-motion` means **gentler, not zero**. Transforms and movement go;
opacity and color transitions stay, because they aid comprehension. Hover motion is
gated behind `@media (hover: hover) and (pointer: fine)`.

---

## 6. Data honesty

The rules that decide what a screen is allowed to show.

- **No placeholder numbers.** Every figure on every screen comes from the database
  (`api/routes/screens.py`, `api/routes/briefing.py`, `api/routes/journal.py`). The
  previous build's `previewData.ts` is deleted.
- **Missing is missing.** A holding the last run didn't price shows `—` for market
  value and says why; it is never back-filled with a guess or shown as `$0`.
- **Empty is an answer.** "Nothing on watch" is a result, not a gap, and says so.
- **Not enough data is stated, not drawn.** Performance needs two readings to draw a
  line; below that it says "Not enough history yet — check back after a few runs"
  rather than plotting one dot.
- **Say what a number isn't.** Performance names its readings a log rather than a
  track record, because early NAV snapshots predate the full book being priced.

---

## 7. Writing

- Sentence case for headings and prose. Title Case for stat labels only (the
  reference's convention).
- Spell units out: `1 share`, not `1 sh`. `13.8% of portfolio`, not `13.8%`.
- Plain English before jargon, with the mechanism available on expand.
- No exclamation marks. No "Oops!". Errors are direct and active: *"Can't reach the
  Z Money API."*
- Backend enum and key names are humanized for display (`src/lib/humanize.ts`):
  `PROFIT_BAND` → "Profit band", `ai_semis` → "AI semis".
