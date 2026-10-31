# ARIA web design

ARIA's look is "a greenhouse on cream paper". It came with a written style reference and a
screen recording of a real site. Where the two disagree, this file follows the recording,
because it shows a real site. For example, the reference describes uppercase eyebrow labels,
but the recording shows small sentence-case tags, so ARIA uses those.

This file adapts the reference to an incident-triage product. It is the source of truth for
every page in `web/`, and the explainer video in `video/` follows it too (`video/src/theme.ts`).

## Idea: a greenhouse on cream paper

The site reads like a calm, editorial field guide to an incident:

- the page is warm cream paper;
- tinted panels lie on it in layers: keylime, mint, sage and slate;
- one deep forest ink carries every heading, link and main action;
- the product itself is the imagery, as cream cards from a real recorded run on a slate panel;
- a forest-ink line drawing is the one illustration: many loose lines that run together into
  one, the logs becoming a single incident. The logo carries the same idea.

The console keeps the same paper, ink and panels on a slightly warmer canvas, so cream cards lift
off it.

## Principles

1. **Layers, not shadows.**
   - Depth comes only from the stack: cream (the page and cards), then keylime, mint, sage and
     slate panels.
   - There are no drop shadows and no coloured card borders. A neutral hairline (`--rule`)
     marks a card when it sits on cream.
2. **A serif for pages and sections, a firm sans for everything inside them.**
   - Newsreader sets page titles (`h1`), the landing page's sections and large statistics, at
     weight 350 to 400 and never smaller than 28 px, so no title is thin.
   - Inter at weight 600 sets the titles inside a page (`h2` and `h3`: panels, cards, steps), so
     each stands apart from the text under it at a glance.
   - Inter sets everything else: body, navigation, labels and buttons.
   - Geist Mono sets log lines, IDs and commands.
3. **One saturated dark.**
   - Forest ink `#0f3e17` is the only strong colour. It is used for headings, links, focus rings
     and every main action.
   - The panels are surfaces only and never carry text colour.
4. **Product first.**
   - Show what ARIA does with real data (the recorded run, real evaluation results) rather than
     decoration.
   - Every measured number comes from the generated data files, never typed by hand.
5. **Generous and left-aligned.**
   - Sections are left-aligned, with a small tag, the serif heading and a short subhead.
   - Cards get 28 to 42 px of padding, and sections 64 to 96 px of space between them.

## Colour

All pairs were measured for WCAG 2.2 AA: 4.5:1 for text, and 3:1 for control edges and focus.

| Token                | Light                 | Night             | Use                                                |
| -------------------- | --------------------- | ----------------- | -------------------------------------------------- |
| `--background`       | `#fffefc` cream paper | `#0f1a13`         | The landing page                                   |
| `--app`              | `#f5f4ef`             | `#0b140e`         | The console's canvas                               |
| `--raised`           | `#fffefc`             | `#16231a`         | Cards                                              |
| `--sunken`           | `#f2f1eb`             | `#0b140e`         | Wells: inputs, code, bar tracks                    |
| `--heading`          | `#0f3e17` forest      | `#f4f8f2`         | Headings and links (12.1:1 on cream)               |
| `--foreground`       | `#222222` charcoal    | `#e8efe6`         | Body text                                          |
| `--muted-foreground` | `#3f4a42`             | `#b5c3b8`         | Secondary text, 5.6:1 even on slate                |
| `--faint`            | `#4b564e`             | `#9aab9e`         | Tertiary text, 4.7:1 on slate                      |
| `--rule`             | `#efeeeb`             | leaf at 10%       | Hairlines                                          |
| `--control`          | `#737b75`             | `#7e9184`         | Control edges (3.6:1 on cream)                     |
| `--primary`          | forest                | keylime `#e1f4df` | The main action; its text is cream (night: forest) |
| `--panel-keylime`    | `#e1f4df`             | `#18291c`         | The lightest panel                                 |
| `--panel-mint`       | `#cfe7d3`             | `#1c3022`         |                                                    |
| `--panel-sage`       | `#b1dbb8`             | `#24402c`         | The heaviest green panel                           |
| `--panel-slate`      | `#b6ced5`             | `#1e2f35`         | The cool counter-panel, home of product cards      |
| `--highlight`        | mint                  | `#2a4a32`         | Selection and the evidence sweep                   |

Severity keeps its own earthy hues, apart from the greens, so a level never reads as decoration:

- **Fills** (labels on them are ink): terracotta `#e9826e`, apricot `#f1aa6a`, wheat `#ead27c`
  and slate blue `#a8c6cf`.
- **Text versions** (`--sevN-fg`), each 6.7:1 or more on cream.

## Type

| Role                              | Face           | Size               | Notes                                     |
| --------------------------------- | -------------- | ------------------ | ----------------------------------------- |
| Hero (`.text-hero`)               | Newsreader 350 | 48 to 76 px        | -0.03em, line height 1.04                 |
| Section opener (`.text-display`)  | Newsreader 400 | 38 to 60 px        | -0.03em                                   |
| Section heading (`.text-section`) | Newsreader 400 | 32 to 44 px        | -0.01em                                   |
| Page title (`h1`)                 | Newsreader 400 | 40 to 44 px        | -0.01em                                   |
| Console section (`SectionHeader`) | Newsreader 400 | 32 px              | Groups a long page's cards                |
| Panel, card and step title        | Inter 600      | 20 to 27 px        | `h2` and `h3`                             |
| Statement (`.text-statement`)     | Newsreader 400 | 24 to 30 px        | Forest                                    |
| Subhead (`.text-lead`)            | Inter 400      | 19 to 22 px        | Muted                                     |
| Body                              | Inter 400      | 18 px (help 16 px) | Charcoal                                  |
| Tag (`.tag`)                      | Inter 500      | 14 px              | Sentence case on a slate (or cream) label |
| Stat (`.stat`)                    | Newsreader 400 | 48 px and up       | Lining, tabular figures                   |

The scale is 14, 16, 18, 20, 23, 27, 32, 44, 60 and 78 px (`--text-xs` to `--text-6xl`). It was
raised twice on owner feedback: the text was too small, then text and titles read as one size.
Each step above body grows by about an eighth, so a title stands clear of the text under it.
The floor is 14 px for text; labels drawn inside a chart may go to 12 px.

## Shape

- Cards and large buttons have 14 px corners (`rounded-card`, `rounded-lg`).
- Medium buttons have 10 px corners, and small controls and nav items 7 px.
- Tags have 4 px corners, and badges and status pills are full pills.

## Space and measure

- Spacing keeps to a scale of 8, 16, 24 and 32 px: 8 px inside a group, 16 px between groups,
  24 px between panels and 32 px between a page's sections. Landing sections take more room.
- Running text stops at about 65 characters a line (`max-w-prose`), at every size.
- A view shows at most four badges. Long lists say a level with a dot and its name instead.
- Anything clickable is at least 24 px tall, links set in small text included.

## Components

- **Navigation.** The name on the left, the sections in charcoal, and "Open the console" as the
  cream button with a hairline on the right (the hero holds the page's one forest action). A keylime pill marks the section being read (the sliding nav
  pill). On a wide screen the theme button sits beside the console button; below that, one menu
  holds the sections, GitHub and the theme.
- **Hero.** A sage panel holds the serif headline, which names the outcome, and the summary, which
  names who it is for; beneath it sits a full-width forest button, "Try it on real logs". To the
  right, a slate panel holds one cream card from the recorded run: the level, one claim with its
  citation open on the log line it cites, and a status that is plainly not a button.
- **Sections.** The home page shows ARIA off (owner request, round 9), each section a tag, a
  heading, a sentence or two and one picture:
  - the hero;
  - the problem and the answer: the line drawing still apart on cream, then running together on
    a full-width sage band;
  - what it does: four cards, and the explainer video with what it shows written out beneath it;
  - how it works: a carousel of the four steps, each shown on the recorded incident;
  - the example incident to explore;
  - the results: one row of findings, each linked to its test;
  - the way in, where the drawing's lines run on to the edge, and the footer.
- **Carousel.** Tabs name the four steps, and a thin line under the current one fills as it
  plays. It moves on by itself every nine seconds and slows to a quarter of that pace while a
  pointer rests on it. Keyboard focus inside it, the Pause button, a hidden browser tab or
  scrolling it off screen stop it, and with reduced motion it starts paused. Arrow keys move
  between the tabs. It is the only part of the site that moves on its own (WCAG 2.2.2).
- **Cards.** Cream with a hairline, a keylime icon tile holding a forest line icon, a serif
  title and muted body text.
- **FAQ.** Rows with the question in the serif on the left and the answer in the sans on the
  right, a hairline between rows. Every answer is visible.
- **Console.** A cream sidebar panel on the warm canvas, with keylime for the active item; cards
  are cream, and the main action is forest.

## Motion

Motion is unhurried: a fast start and a gentle settle (`cubic-bezier(0.16, 1, 0.3, 1)`). Only
transform, opacity and the stroke dash offset animate, and everything stops under
`prefers-reduced-motion`. Nothing moves on its own for longer than five seconds without a way
to stop it (WCAG 2.2.2).

- **Line art.** Each drawing's strokes draw in once as it comes into view.
- **The six chosen animations:**
  - the hero entrance: the report card rises into place once;
  - the sliding nav pill;
  - numbers that roll into view;
  - the severity stamp and the prediction-set bracket;
  - the highlight that sweeps across cited evidence;
  - the dot bloom on ghost buttons.

## Icons and illustration

- Icons are Lucide line icons at 1.5 px in forest ink, often on a keylime tile.
- The mark is a forest square in which three lines run together into one (`components/aria/
wordmark.tsx`, `app/icon.svg`), beside a lowercase serif "aria".
- The console's quiet moments (a first visit, an empty queue, a search with no match, a missing
  page) use small line drawings in the same hand (`components/illustrations/spots.tsx`).

## Checks

- `make web-check`: format, lint, typecheck and unit tests.
- `make web-e2e`: Playwright with axe in both themes.
- `make web-lighthouse`: desktop at 95 or more, and the mobile gate at 90.
