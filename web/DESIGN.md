# ARIA web design

ARIA's look follows the **MindMarket** style reference the owner chose: "a warm storybook on
cream paper". The owner supplied a written style spec and a screen recording of the reference
site. Where the two disagree, this file follows the recording, because it shows the real site.
For example, the spec gives 50 px corners to buttons and cards, but the recording shows small
corners on those and 50 px only on whole page panels.

This file adapts that reference to an incident-triage product. It is the source of truth for
every page in `web/` and for the video in `video/`.

## Idea: a storybook on cream paper

The site reads like a picture book about the night shift:

- the page is cream paper;
- cards are white sheets lifted off it, and wells are sandstone pressed into it;
- whole panels of fresh grass open and close the page;
- flat, playful characters act out what ARIA does: riding a long sheet of log lines,
  stamping a severity, looking closer at pinned evidence, and giving a thumbs-up before
  anything is sent.

The console keeps the same paper, ink and green, but is calmer: illustrations appear only in
quiet moments (a first visit, an empty queue, a search with no match, a missing page).

## Principles

1. **Paper, not shadow.**
   - Depth comes only from the stack: cream (the page), white (cards, the floating nav),
     sandstone (wells, code, log panes).
   - There are no drop shadows and no gradients anywhere.
2. **One face, two weights.**
   - Inter only, at 400 (body) and 500 (headings, labels, buttons). Never bold.
   - Code and log lines use Inter too, with its disambiguation set (`ss02`: slashed zero, I with
     serifs, l with a tail) and tabular figures. This keeps `Il1` and `0O` distinct without a
     second typeface.
3. **Big, tight headlines.**
   - The display size runs from 53 px on a phone to 144 px on a wide screen (`.text-display`),
     at line height 0.95 and -0.06em.
   - Section headings are 81 px on wide screens and 53 px on tablets, at -0.04em. Lead
     paragraphs are 30 px at -0.03em.
   - Labels are sentence case. There are no uppercase tracked labels.
4. **One structural green.**
   - Fresh grass (#8ed462) fills whole panels, the active item, toggles that are on, and the
     round arrow on buttons.
   - It is a fill under ink, never text: grass on cream is 1.6:1.
5. **Pops are decoration, one per component.**
   - Sky, coral, sunshine and lilac colour the story cards' buttons (one each), the chromatic
     dots beside section names, and the characters' clothes.
   - The footer band is sunshine yellow.
   - A pop never means a state: severity has its own hues (principle 7).
6. **Crisp corners, round panels.**
   - 6 px for bars, buttons and inputs; 8 px for cards; 4 px for tiny tags.
   - Circles for icon buttons and the arrow on calls to action.
   - 50 px (`rounded-sheet`) only for whole page panels: the cream page laid over the green
     hero, and the closing green panel over the yellow footer.
7. **Severity is functional, and labelled.**
   - SEV1 to SEV4 are rose, orange, mustard and slate. They are kept apart from the pops, so a
     coral button never reads as "critical".
   - Each strip carries its label in ink, so colour is never the only cue.
8. **Every claim shows its evidence.**
   - Citations (`E12`) are buttons. Hovering shows the evidence beside the claim, focusing fills
     the evidence panel (announced to screen readers), and clicking pins it there.
   - This is ARIA's core interaction and survives every restyle.
9. **Motion answers people.**
   - Presses scale to 98%, and the round arrow nudges right on hover.
   - The landing page plays the recorded run in as it scrolls past (wide screens only).
   - Larger animations are proposed to the owner and built only when chosen. The owner chose
     these six:
     - **Hero entrance:** the scene settles in once, back to front (about 1.2 s), then its loose
       pages keep drifting. CSS on the scene's groups (`scenes.tsx`, `.hero-in`, `.hero-drift`).
     - **Sliding nav pill:** a grass pill glides to the section being read on the landing page,
       and between pages in the console sidebar. It moves by FLIP, so only transforms animate.
     - **Rolling stats:** headline numbers roll up digit by digit as they come into view
       (`RollingNumber`). The real value is always in the page as text.
     - **Severity stamp:** a new severity lands like a rubber stamp, then the prediction-set
       bracket draws across the bars (`.sev-stamp`, `.sev-bracket`, and the replay's timeline).
     - **Evidence thread:** pointing at a citation sweeps the highlight across each line it cites
       (`.thread-lit` on the landing page, one pass of light, `.thread-pass`, in a run's panel).
     - **Dot bloom:** a ghost button's hover and focus fill grows out of a dot at its centre.
   - Every animation moves only `transform` and `opacity`, so it runs on the compositor at 60 fps
     and never shifts layout. Anything that starts larger than its box (the stamp) is clipped to
     its card, so a transform can never make a narrow screen scroll sideways.
   - `prefers-reduced-motion` shows final states.

## Tokens

All tokens are defined once in `src/app/globals.css`. Every text pair was measured for WCAG 2.2
AA: 4.5:1 for text, 3:1 for control edges.

### Day (light, the default)

| Token                       | Value                              | Use                                                 |
| --------------------------- | ---------------------------------- | --------------------------------------------------- |
| background                  | #f5f1e4 cream paper                | the page                                            |
| foreground, heading         | #2c2e2a ink                        | text, borders, icons; 12.1:1 on cream               |
| raised                      | #ffffff                            | cards, the floating nav                             |
| sunken                      | #e0dbce sandstone                  | wells, code, inputs                                 |
| rule                        | #d5d5d4 hairline mist              | dividers                                            |
| control                     | #80827f stone grey                 | control edges, link underlines; 3.4:1 on cream      |
| muted-foreground            | #50524e                            | secondary text; 6.9:1 on cream, 5.7:1 on sandstone  |
| faint                       | #5d5f5a                            | quieter text; 4.7:1 even on sandstone               |
| primary                     | ink                                | focus rings, selected edges                         |
| grass                       | #8ed462                            | panels, active item, toggles; ink on it is 7.7:1    |
| grass-deep                  | #6fbf3f                            | hills, pressed green; ink on it is 6.0:1            |
| sky, coral, sunshine, lilac | #2ba0ff, #ff705d, #f5e211, #ebc0ff | decoration; ink on each is 5.0, 5.1, 10.3 and 8.8:1 |

Stone grey, as the spec gives it, fails 4.5:1 for small text on cream. It draws edges and
underlines, and small muted text uses the deeper greys above.

### Night (dark)

This is the same paper after dark:

- the page is warm ink (#1f211c), cards are #2b2e28 and wells are #171915;
- text is cream, with #c9c6b9 for muted text and #aeab9f for faint text;
- grass and the pops are unchanged, and always carry ink text;
- the hero, the closing panel and the footer keep their colours, with ink text.

### Severity

| Level | Strip                         | Text colour (on cream) |
| ----- | ----------------------------- | ---------------------- |
| SEV1  | rose `oklch(0.72 0.15 15)`    | `oklch(0.5 0.17 20)`   |
| SEV2  | orange `oklch(0.8 0.14 60)`   | `oklch(0.5 0.12 55)`   |
| SEV3  | mustard `oklch(0.87 0.13 95)` | `oklch(0.48 0.1 90)`   |
| SEV4  | slate `oklch(0.83 0.04 235)`  | `oklch(0.46 0.05 240)` |

Strip labels are ink, from 5.2:1 (SEV1) up.

### Type

- Inter (SIL OFL), self-hosted from Fontsource. The file carries the optical-size axis, so
  `font-optical-sizing: auto` gives the 144 px headline Inter's display cut.
- The scale in pixels is 13, 15, 16, 18, 20, 30, 36, 53, 64 and 81, plus the display size.

### Space and layout

- The content is at most 1200 px wide (`max-w-[75rem]`). The console runs wider (1440 px) for
  tables.
- Sections are 80 to 112 px apart, and cards are padded 28 to 48 px.
- The landing page is one editorial column. Cards alternate sides along the green road.

## Components

- **Floating navigation.** Two white bars, 6 px corners, 16 px from the top, fixed while
  scrolling:
  - the left bar holds the mark and name, the section links, and a round grass menu button;
  - the right bar is "Open the console" with a small face in a sky disc (the reference's
    chromatic dot).
  - Below 360 px only the face shows; the link's name stays "Open the console".
- **Call to action.** A label and a round arrow. The button is white on cream or grass with a
  grass arrow, or a pop with a white arrow on story cards. On hover the arrow nudges right.
- **Primary button (console).** Grass fill, ink text. One per view.
- **Secondary and ghost buttons.** A faint ink tint, or transparent.
- **Story card.** White, 8 px corners, a 36 to 53 px heading, a 20 px body, and one pop button.
- **Section label.** Sentence case, with a chromatic dot (one pop per section). It names the
  section the navigation links to.
- **Statistic.** An ink number in Inter 500, tight, with tabular figures and its label below.
  In the console, words such as "None yet" are set smaller and in muted grey.
- **Console sidebar.** A floating white panel on the cream page. It holds the search button
  (the command palette), then links grouped under Triage, Knowledge and System. The current
  page is a grass row.
- **Command palette.** It opens with Ctrl or Cmd + K, "/", or the search button. It is an ARIA
  combobox over a grouped listbox: pages, recent incidents, samples, words and actions. The
  selected row is grass.
- **Shortcuts sheet.** It opens with "?". "g" then a letter goes to a page, and a switch turns
  single-key shortcuts off (WCAG 2.1.4). Approval never has a shortcut.
- **Illustrations.** Flat SVG built from one kit (`src/components/illustrations/kit.tsx`):
  - bean torsos, round heads, rubber-hose limbs drawn as thick round-capped curves, and thin
    ink lines for faces and fingers;
  - skin tones include stylised blue and lilac, as in the reference;
  - every scene is decorative (`aria-hidden`) and repeats what its text says;
  - scenes cost only their markup: no images, no script.

## Where things live

- `src/app/globals.css`: tokens and the display, lead, label, statistic and link utilities.
- `src/components/illustrations/`:
  - `kit.tsx`: the cast and props;
  - `scenes.tsx`: the landing page's scenes;
  - `spots.tsx`: the console's small scenes.
- `src/components/aria/`: the mark and wordmark, severity badges and the severity instrument
  (model probabilities, the conformal set bracket, the safety floor).
- `src/components/ui/`: shadcn/ui-style primitives on Radix, restyled with the tokens above.
  The shadcn registry, 21st.dev and React Bits were unreachable from the build environment, so
  these were written in this repo in the same pattern.
- `src/components/site/`: the landing page (`story.tsx` is the green road). Its numbers come
  from `src/data/*.json`, copied from `docs/` (`pnpm sync:data`) and from one recorded run
  (`scripts/record_demo_run.py`).
- `src/components/console/` and `src/components/run/`: the console, including
  `command-palette.tsx`.

## Do

- Keep backgrounds to cream, white, sandstone, grass panels and the sunshine footer.
- Put ink text on grass and on every pop.
- Keep one pop per component, and a pop's meaning decorative.
- Keep headings at Inter 500 with negative tracking.
- Use 50 px corners only for whole page panels.

## Do not

- Use drop shadows, gradients, bold weights or a second typeface.
- Use grass or a pop as a text colour or as the only sign of a state.
- Put white cards on white, or set small text in stone grey.
- Set display text below 53 px.
