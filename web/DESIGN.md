# ARIA web design

ARIA's look follows the **Auros** style reference the owner chose, described as an "abyssal
terminal with bioluminescent data orbs". This file records that reference, adapted to an
incident-triage product. It is the source of truth for every page in `web/` and for the video in
`video/`.

## Idea: an abyssal terminal

The interface is a deep-water instrument panel:

- a near-black teal canvas;
- content surfaces that sit at different depths of the same hue;
- one bioluminescent data orb: a rotating particle sphere, the brand's visual.

It is sparse and cinematic. One geometric face at medium weight builds scale through size and
tight tracking, not weight. Colour is rationed:

- achromatic whites and silvers carry the content;
- the chromatic palette is reserved for the orb, one gradient call to action, and the large
  lavender statistics.

Hierarchy reads as depth of water, not shadow on paper.

## Principles

1. **Depth, not shadow.**
   - Surfaces step through the teal stack: abyss (canvas), deep (recessed wells such as log
     panes and the footer), kelp (raised cards).
   - There are no drop shadows anywhere, and cards have no visible border; hairlines are 10%
     white at most.
2. **One weight for display.**
   - Every heading uses the display face at weight 500, never bold, never light.
   - Large sizes take negative tracking: -0.04em at 61 px, -0.046em at 86 px and above.
   - Body copy is weight 400.
3. **Instrument labels.**
   - Section labels, kickers, table headers and nav links are uppercase and tracked, at
     0.12em (12 px) or 0.08em (20 px), in silver or mist.
4. **Rationed colour.**
   - White is for headings and nav only; body text is mist (emphasis) or silver (secondary).
   - Lavender phosphor is only for large statistics.
   - The aurora gradient is only for the single most important action in a view: one button,
     never a background, border or text.
5. **Two radii.** 16 px for cards and panels, 6 px for everything small (buttons, inputs,
   badges, chips).
6. **Severity is the one functional exception.**
   - An incident tool must show severity at a glance, so SEV1 to SEV4 keep a restrained hue
     each, tuned to sit inside the aurora palette: coral, amber, pale gold, aqua-silver.
   - Each severity always carries its label in dark ink, so colour is never the only cue.
7. **One moving thing per view.** The orb on the landing page, and a run's live progress in the
   console. Everything else is still. `prefers-reduced-motion` shows final states and a static
   orb.
8. **Every claim shows its evidence.**
   - Citations (`E12`) are buttons: hovering shows the evidence beside the claim, focusing fills
     the evidence panel (announced to screen readers), and clicking pins it there.
   - This is ARIA's core interaction and survives every restyle.

## Tokens

All colour tokens are OKLCH, defined once in `src/app/globals.css`, converted from the
reference's hex values. Every text pair was checked for WCAG 2.2 AA: 4.5:1 for text, 3:1 for
control edges.

### Night (dark, default): the Auros palette

| Token              | Reference name    | Hex          | OKLCH                      | Use                                           |
| ------------------ | ----------------- | ------------ | -------------------------- | --------------------------------------------- |
| `background`       | Liquid Abyss      | `#012624`    | `oklch(0.243 0.041 189.5)` | canvas, header, hero                          |
| `sunken`           | Liquid Deep       | `#011d1c`    | `oklch(0.209 0.035 191.6)` | recessed wells: log panes, footer, code       |
| `raised`           | Liquid Kelp       | `#003734`    | `oklch(0.304 0.053 188.9)` | cards and panels, secondary buttons           |
| `heading`          | Platinum          | `#ffffff`    | `oklch(1 0 0)`             | headings, nav, icon strokes                   |
| `foreground`       | Liquid Mist       | `#edfffe`    | `oklch(0.987 0.019 192.8)` | body text and emphasis                        |
| `muted-foreground` | Silver Mist       | `#bbc7c6`    | `oklch(0.820 0.013 190.9)` | secondary text, labels, resting links         |
| `faint`            | (derived)         | `#93a3a2`    | `oklch(0.703 0.018 192.2)` | tertiary text (5.0:1 on kelp, 6.1:1 on abyss) |
| `control`          | Slate Deep        | `#707777`    | `oklch(0.563 0.008 196.9)` | input edges on the canvas (3.5:1)             |
| `stat`             | Lavender Phosphor | `#fde9ff`    | `oklch(0.956 0.036 323.1)` | large statistics only                         |
| `primary`          | (aurora start)    | `#cbfffc`    | `oklch(0.964 0.053 191.9)` | focus rings, links, active nav, highlights    |
| `rule`             |                   | white at 10% |                            | hairlines and separators (decorative)         |

Gradients:

- **Aurora** (`--gradient-aurora`, the primary call to action): `linear-gradient(90deg,
#cbfffc 0%, #edfffe 26.25%, #fffdfa 47.57%, #fad1ff 88.96%)`, with dark ink text.
- **Bioluminescent** (`--gradient-bio`, the orb and data accents): `linear-gradient(90deg,
#00827c 0%, #cbfffc 100%)`.

Contrast on the canvas and on cards:

| Text     | On abyss | On kelp |
| -------- | -------- | ------- |
| Mist     | 15.6:1   | 12.7:1  |
| White    | 16.1:1   | 13.2:1  |
| Silver   | 9.3:1    | 7.6:1   |
| Lavender | 14.0:1   | 11.5:1  |
| Aqua     | 14.8:1   | 12.1:1  |

Slate fails as text (3.5:1 on the canvas, 2.9:1 on cards), so it only marks control edges on the
canvas; inputs on cards use `faint`. Teal `#00827c` is decoration only (3.4:1).

### Day (light)

The build brief asks for a light theme as well. It inverts the same hue:

- a mist canvas with white cards;
- Liquid Deep ink for text and Liquid Kelp for actions;
- darker severity text variants.

The aurora call to action and the orb keep their colours.

### Severity

| Severity | Night strip                        | Meaning            |
| -------- | ---------------------------------- | ------------------ |
| SEV1     | coral `oklch(0.74 0.15 18)`        | critical: page now |
| SEV2     | amber `oklch(0.83 0.12 68)`        | major              |
| SEV3     | pale gold `oklch(0.91 0.1 100)`    | moderate           |
| SEV4     | aqua-silver `oklch(0.85 0.05 195)` | minor              |

Labels sit on the strip in Liquid Deep ink (over 7:1 on every strip).

### Type

- **Display and body: Geist (variable, SIL OFL 1.1, from Fontsource).**
  - The reference specifies Matter, a commercial face. Geist is the closest open match: a
    geometric grotesque with the same engineered, instrument-like confidence at weight 500
    with tight tracking.
  - The reference's own suggestions (Inter, DM Sans, Satoshi) were compared side by side.
    Inter is too neutral, DM Sans too soft, and Satoshi ships under the Fontshare licence
    rather than an open font licence.
- **Machine text: Geist Mono.** For log lines, IDs and evidence. It keeps `0 O`, `1 l I |` and
  `rn m` distinct.

| Role              | Size        | Line height | Tracking | Weight        |
| ----------------- | ----------- | ----------- | -------- | ------------- |
| Label (uppercase) | 12 px       | 1.4         | 0.12em   | 500           |
| Body              | 16 px       | 1.4 to 1.5  | 0        | 400           |
| Subheading        | 24 px       | 1.3         | -0.02em  | 500           |
| Heading           | 36 px       | 1.0         | -0.02em  | 500           |
| Heading large     | 61 px       | 1.0         | -0.04em  | 500           |
| Display           | 96 px       | 1.0         | -0.04em  | 500           |
| Statistic         | 61 to 86 px | 1.0         | -0.046em | 500, lavender |

No text is smaller than 12 px, and numbers that line up use tabular figures.

### Space and layout

- **Grid:** 4 px base.
- **Section gap:** 68 px or more.
- **Card padding:** 36 to 48 px on the landing page, 24 px in the dense console.
- **Element gap:** 20 px.
- **Widths:** a 1440 px maximum page width; long text in columns of about 600 px.
- **Motion:**
  - Four durations (80, 140, 220, 360 ms) and three easings, shared by CSS and GSAP.
  - The orb runs on `requestAnimationFrame` only while it is visible and the tab is open. It
    starts once the page has loaded (phones wait a further 1.2 s), and holds one still frame
    under reduced motion.
  - Its start is split across an idle callback and a frame, and the canvas is only sized then,
    so no step of it is a long task, even on a throttled phone.

## Components

- **Aurora button (primary call to action).**
  - The aurora gradient, 6 px radius, dark ink text at 14 px, uppercase with 0.08em tracking.
  - One per view at most.
- **Kelp button (secondary).** Liquid Kelp fill, white text, 6 px radius.
- **Ghost button.** Transparent, silver text, white on hover.
- **Surface card.** Kelp fill, 16 px radius, no border, no shadow. A white heading at weight
  500, and silver body text.
- **Recessed well.** Deep fill, 16 px radius. Used for log panes, code, and the footer band.
- **Arrow icon button.** 32 x 32, 6 px radius, a faint mist fill, with a thin ↗ arrow. Sits
  right of a card title as its link, and its hit area covers the whole card.
- **Section label.** Uppercase, tracked, silver, above a heading. It names the section; it is
  never decoration.
- **Statistic.** A lavender number with an uppercase tracked label below in mist.
- **Severity badge.** The severity strip colour, a 6 px radius, and the label in dark ink.
- **Navigation bar.** Transparent, 80 px tall: the wordmark left, uppercase tracked links that
  match the section labels, and a kelp "Console" button right (the hero carries the aurora).
- **Console sidebar.** A deep well. Links sit in sentence case for scanning, grouped under
  uppercase labels: Triage, Knowledge, System. The current page is a kelp row with an aqua icon.
- **The orb.** A canvas particle sphere on a Fibonacci sphere: teal at the back, white at the
  front, lavender at the rim, with a thin shell of drifting dust and the odd near point flaring
  like data arriving.
  - It is decorative (`aria-hidden`), rises behind the hero's text and fades out under it.
  - It must never delay the largest paint, and a CSS glow stands in for it until it starts.
  - Up to 3,600 points with a mouse (the orb tilts a little towards the pointer). Touch screens
    get 1,100 points at 1x resolution and half the frame rate.

## Where things live

- `src/app/globals.css`: tokens, gradients and the label, statistic and display utilities.
- `src/components/aria/`:
  - the severity badge and the severity instrument (model probabilities, conformal set
    bracket, safety floor);
  - the orb (`orb.tsx`).
- `src/components/ui/`:
  - shadcn/ui-style primitives on Radix, restyled with the tokens above;
  - the shadcn registry, 21st.dev and React Bits were unreachable from the build environment,
    so these were written in-repo in the same pattern (`components.json` is compatible with
    the shadcn CLI).
- `src/components/site/`:
  - the landing page;
  - its numbers come from `src/data/*.json`, copied from `docs/` (`pnpm sync:data`) and from
    one recorded run (`scripts/record_demo_run.py`).
- `src/components/console/` and `src/components/run/`: the console.

## Do

- Use only the teal surface stack for backgrounds.
- Keep headings at weight 500, with negative tracking at display sizes.
- Track every uppercase label (0.08em to 0.15em).
- Keep the aurora gradient to one call to action per view.
- Keep radii at 16 px (cards) and 6 px (small).

## Do not

- Use drop shadows, bold or light display weights, white body text, or radii above 16 px.
- Put light text on the aurora gradient or on lavender.
- Introduce colours outside the teal scale, the silver neutrals, lavender, and the four
  severity strips.
