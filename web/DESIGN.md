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
2. **A light serif and a quiet sans.**
   - Newsreader at weight 300 sets every headline (`h1` to `h3`) and editorial statement. It is
     never bold.
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

| Role                              | Face           | Size                  | Notes                                     |
| --------------------------------- | -------------- | --------------------- | ----------------------------------------- |
| Hero (`.text-hero`)               | Newsreader 300 | 44 to 68 px           | -0.03em, line height 1.04                 |
| Section opener (`.text-display`)  | Newsreader 300 | 36 to 56 px           | -0.03em                                   |
| Section heading (`.text-section`) | Newsreader 300 | 30 to 40 px           | -0.01em                                   |
| Statement (`.text-statement`)     | Newsreader 300 | 23 to 28 px           | Forest                                    |
| Subhead (`.text-lead`)            | Inter 400      | 15 to 18 px           | Muted                                     |
| Body                              | Inter 400      | 15 px (console 14 px) | Charcoal                                  |
| Tag (`.tag`)                      | Inter 500      | 12 px                 | Sentence case on a slate (or cream) label |
| Stat (`.stat`)                    | Newsreader 300 | 48 px and up          | Lining, tabular figures                   |

The floor is 12 px; the reference's 10 and 11 px labels are raised to it.

## Shape

- Cards and large buttons have 14 px corners (`rounded-card`, `rounded-lg`).
- Medium buttons have 10 px corners, and small controls and nav items 7 px.
- Tags have 4 px corners, and badges and status pills are full pills.

## Components

- **Navigation.** The name on the left, the sections in charcoal, and "Open the console" as the
  cream button with a hairline on the right (the hero holds the page's one forest action). A keylime pill marks the section being read (the sliding nav
  pill). On a wide screen the theme button sits beside the console button; below that, one menu
  holds the sections, GitHub and the theme.
- **Hero.** A sage panel holds the serif headline, which names the outcome, and the summary, which
  names who it is for; beneath it sits a full-width forest button, "Try it on real logs". To the right, a slate panel
  holds one cream card from the recorded run: the level, one claim with its citation open on the
  log line it cites, and a status that is plainly not a button. Below, three bordered tiles each
  link to the proof of one claim (the test results, the example, the review step).
- **Sections.** Eight, each a tag, a heading, a sentence or two and one picture: the hero, what
  ARIA does (four cards and the explainer video), the example incident, how it works in four
  steps, the results (one row of four findings, each linked to its test), try it, questions and
  the footer. Nothing loops: the results are a still row, not a ticker.
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
