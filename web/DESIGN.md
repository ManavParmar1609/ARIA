# ARIA web design

The console is read by someone who has just been paged. The design follows from that reader.

## Idea: triage tags on a night desk

Triage comes from emergency medicine, where every casualty gets a tag with a colour strip that
says how urgent they are. ARIA gives every incident the same thing: a tag whose strip is its
severity, with a punched hole and a perforated edge, and a body that holds the evidence. The tag
appears in the landing page's hero, in every list of runs, and at the top of each run.

## Principles

1. **Legible at 3 a.m.** Atkinson Hyperlegible Next and Mono (Braille Institute) keep easily
   confused characters (`1 l I`, `0 O`, `rn m`) apart, which matters in block IDs and log lines.
   No text below 12 px; tabular figures wherever numbers line up.
2. **Every claim shows its evidence.** Citations (`E12`) are buttons: hovering shows the evidence
   beside the claim, focusing fills the evidence panel (announced to screen readers), clicking
   pins it there.
3. **Colour means severity or state.** The interface is ink and paper; colour appears only for
   severity, for run state, and for the one accent that marks what you can act on.
4. **One moving thing.** Motion shows a run's progress (the landing page's replay and graph,
   the live run view). Everything else is still. `prefers-reduced-motion` shows final states.

## Tokens

Colour is OKLCH, defined once in `src/app/globals.css` and mapped onto shadcn/ui's names. Every
text pair was checked for WCAG 2.2 AA (4.5:1 for text, 3:1 for control edges) in both themes.

| Token        | Night shift (dark, default)                  | Day shift (light)                 | Use                       |
| ------------ | -------------------------------------------- | --------------------------------- | ------------------------- |
| background   | `oklch(0.235 0.03 258)`                      | `oklch(0.975 0.005 258)`          | page                      |
| raised       | `oklch(0.27 0.032 258)`                      | white                             | panels, tags              |
| sunken       | `oklch(0.205 0.028 258)`                     | `oklch(0.95 0.008 258)`           | log wells, inputs         |
| foreground   | `oklch(0.955 0.012 85)`                      | `oklch(0.25 0.03 258)`            | text                      |
| primary      | manila `oklch(0.86 0.07 84)`                 | ink `oklch(0.3 0.06 258)`         | actions, focus, highlight |
| sev1 to sev4 | red, orange, yellow, steel at L 0.68 to 0.87 | same strips, darker text variants | severity                  |

Severity strips always carry their label (`SEV2`) in dark ink, so colour is never the only cue.

Type: a major-third scale from 12 px (`--text-xs`) to 88 px (`--text-6xl`), display weight 800
with -0.03em tracking. Spacing is Tailwind's 4 px grid. Radii are 2 px (tags), 4 to 6 px
(controls and panels) and 10 px (dialogs). Motion uses four durations (80, 140, 220, 360 ms) and
three easings, shared by CSS and GSAP.

## Where things live

- `src/components/aria/`: the tag strip, severity badge and the severity instrument (model
  probabilities, conformal set bracket, safety floor).
- `src/components/ui/`: shadcn/ui-style primitives on Radix, styled with the tokens above. The
  shadcn registry, 21st.dev and React Bits were unreachable from the build environment, so these
  were written in-repo in the same pattern (`components.json` is compatible with the shadcn CLI).
- `src/components/site/`: the landing page. Its numbers come from `src/data/*.json`, copied from
  `docs/` (`pnpm sync:data`) and from one recorded run (`scripts/record_demo_run.py`).
- `src/components/console/` and `src/components/run/`: the console.

## Avoided on purpose

All-caps eyebrow labels, gradient washes, identical rounded cards with soft shadows, middle-dot
metadata strings, arrows on links, and monospace for anything but machine text.
