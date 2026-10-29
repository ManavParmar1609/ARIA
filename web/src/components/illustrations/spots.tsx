import { C, Cloud, INK, PaperPlane, Person, SKIN, Sheet, Squiggle } from "./kit";

/*
 * Small scenes for the console's quiet moments: a first visit, an empty queue, a search with no
 * match, a page that does not exist. Decorative only, so each is aria-hidden.
 */

/** Hello: a wave, and a page held out for the first sample. */
export function WelcomeSpot({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 260 220" className={className} aria-hidden focusable="false">
      <Squiggle x={22} y={40} w={46} color={C.lilac} rotate={-14} />
      <circle cx="226" cy="44" r="6" fill={C.sky} />
      <Sheet x={176} y={96} w={40} rotate={10} mark="tick" />
      <Person
        x={118}
        y={168}
        s={0.82}
        lean={4}
        skin={SKIN.tan}
        top={C.coral}
        bottom={C.sky}
        shoe={C.sunshine}
        hair={INK}
        hairStyle="puffs"
        face="grin"
        legBack={{ to: [-20, 56], bend: [-16, 26] }}
        legFront={{ to: [20, 56], bend: [18, 26] }}
        armBack={{ to: [-30, -58], bend: [-38, -14] }}
        armFront={{ to: [62, -6], bend: [34, 10] }}
        handBack="open"
      />
    </svg>
  );
}

/** All clear: nothing waiting, so a cup of something and the papers in a neat stack. */
export function AllClearSpot({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 260 200" className={className} aria-hidden focusable="false">
      <Cloud x={150} y={18} w={90} />
      <g transform="translate(172 150)">
        <rect x="0" y="-12" width="58" height="12" rx="3" fill={C.white} />
        <rect x="4" y="-24" width="54" height="12" rx="3" fill={C.sand} />
        <rect x="-2" y="-36" width="58" height="12" rx="3" fill={C.white} />
      </g>
      <Person
        x={96}
        y={156}
        s={0.8}
        lean={-8}
        skin={SKIN.brown}
        top={C.lilac}
        bottom={C.sunshine}
        shoe={C.coral}
        hair={INK}
        hairStyle="bun"
        face="calm"
        legBack={{ to: [64, 4], bend: [34, -22] }}
        legFront={{ to: [70, -2], bend: [40, -30] }}
        armBack={{ to: [30, 10], bend: [10, 20] }}
        armFront={{ to: [30, -26], bend: [30, 4] }}
      />
      {/* the mug, steaming */}
      <g transform="translate(124 92)">
        <rect x="0" y="0" width="20" height="22" rx="4" fill={C.sky} />
        <path d="M20 6q8 0 8 6t-8 6" fill="none" stroke={C.sky} strokeWidth="4" />
        <path
          d="M5 -6q-4 -6 1 -12M13 -6q-4 -6 1 -12"
          fill="none"
          stroke={INK}
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </g>
    </svg>
  );
}

/** Nothing found: a magnifier over an empty page. */
export function SearchSpot({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 220 180" className={className} aria-hidden focusable="false">
      <Sheet x={60} y={30} w={86} lines={0} />
      <circle
        cx="122"
        cy="98"
        r="34"
        fill={C.white}
        fillOpacity="0.6"
        stroke={INK}
        strokeWidth="7"
      />
      <path d="M146 122l30 30" stroke={C.coral} strokeWidth="12" strokeLinecap="round" />
      <path
        d="M108 86q8 -8 20 -4"
        fill="none"
        stroke={C.white}
        strokeWidth="5"
        strokeLinecap="round"
      />
      <Squiggle x={20} y={140} w={42} color={C.sunshine} rotate={-10} />
      <circle cx="190" cy="40" r="6" fill={C.sky} />
    </svg>
  );
}

/** Lost: a paper plane looping among clouds, for a page that is not there. */
export function LostSpot({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 320 220" className={className} aria-hidden focusable="false">
      <Cloud x={10} y={120} w={130} />
      <Cloud x={190} y={40} w={110} />
      <path
        d="M40 90C80 20 160 30 150 90S70 150 120 170S230 160 250 120"
        fill="none"
        stroke={INK}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray="2 11"
      />
      <PaperPlane x={244} y={96} w={64} rotate={-30} />
      <Squiggle x={200} y={180} w={50} color={C.lilac} rotate={8} />
      <circle cx="60" cy="40" r="7" fill={C.sunshine} />
    </svg>
  );
}
