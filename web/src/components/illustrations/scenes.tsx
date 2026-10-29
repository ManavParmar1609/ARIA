import {
  C,
  Clipboard,
  Cloud,
  INK,
  Magnifier,
  PaperPlane,
  Person,
  SKIN,
  Sheet,
  Squiggle,
  Stamp,
} from "./kit";

/*
 * The landing page's scenes. Each is decorative: the text beside it says the same thing, so every
 * scene is aria-hidden and carries no title.
 */

/** The on-call crew riding a long sheet of log lines: one reads, one looks closer, one points on. */
export function HeroScene({ className, t }: { className?: string; t?: number }) {
  // `t` (seconds) is for the video: the sheet bobs and the loose pages drift. The site leaves it
  // out, so the page draws one still frame.
  const wave = (speed: number, amount: number, phase = 0) =>
    t == null ? 0 : Math.sin(t * speed + phase) * amount;
  return (
    // On narrow screens the page gives the scene a fixed height and it crops to the crew in the
    // middle (slice), rather than shrinking the whole width down to a strip.
    <svg
      viewBox="0 0 1200 600"
      preserveAspectRatio="xMidYMax slice"
      className={className}
      aria-hidden
      focusable="false"
    >
      <Cloud x={0} y={470} w={250} />
      <Cloud x={990} y={110} w={200} />
      <Cloud x={630} y={56} w={110} />

      <g transform={`translate(0 ${wave(1.6, 7)})`}>
        {/* the log sheet, its back end rolled up like a scroll, lines of text along it */}
        <path
          d="M120 500C360 456 540 540 770 450C900 400 1000 350 1090 260L1112 290C1032 380 932 432 802 488C572 582 372 522 140 566Z"
          fill={C.white}
        />
        <ellipse cx="128" cy="533" rx="26" ry="40" fill={C.white} />
        <ellipse cx="131" cy="533" rx="12" ry="21" fill={C.sand} />
        <g fill="none" stroke={INK} strokeWidth="3" strokeLinecap="round">
          <path
            d="M196 514C410 482 576 548 790 466C900 422 984 380 1052 312"
            strokeDasharray="38 12 20 12 52 12 26 12"
          />
          <path
            d="M206 538C420 508 590 566 800 486C908 444 990 404 1070 330"
            strokeDasharray="22 12 44 12 30 12 18 12"
          />
        </g>

        <Sheet x={1000} y={330 + wave(2, 10)} w={50} rotate={16 + wave(1.4, 8)} mark="alert" />
        <Sheet
          x={1112}
          y={150 + wave(1.7, 12, 1)}
          w={40}
          rotate={-12 + wave(1.2, 9, 2)}
          mark="tick"
        />
        <Sheet x={470} y={250 + wave(1.9, 10, 2)} w={44} rotate={-20 + wave(1.5, 7, 1)} />
        <Squiggle x={900} y={190} rotate={-18} w={80} />
        <Squiggle x={230} y={330} w={60} color={C.lilac} rotate={12} />
        <circle cx="960" cy="146" r="8" fill={C.sky} />
        <circle cx="1150" cy="300" r="10" fill={C.sky} />
        <circle cx="290" cy="280" r="7" fill={C.sunshine} />

        {/* reads the run's report */}
        <Person
          x={318}
          y={488}
          s={1.45}
          lean={-10}
          skin={SKIN.brown}
          top={C.sky}
          bottom={C.sunshine}
          shoe={C.coral}
          hair={INK}
          hairStyle="curly"
          face="calm"
          legBack={{ to: [62, 8], bend: [28, -8] }}
          legFront={{ to: [70, 0], bend: [38, -30] }}
          armBack={{ to: [34, -10], bend: [16, 10] }}
          armFront={{ to: [40, -14], bend: [28, 10] }}
        />
        <g transform="translate(392 318) rotate(10)">
          <Clipboard size={1.35} />
        </g>

        {/* looks closer at a line */}
        <Person
          x={606}
          y={434}
          s={1.45}
          lean={20}
          skin={SKIN.peach}
          top={C.coral}
          bottom={C.lilac}
          shoe={C.white}
          hair={INK}
          hairStyle="bun"
          face="focus"
          legBack={{ to: [-38, 46], bend: [6, 52] }}
          legFront={{ to: [42, 46], bend: [46, 2] }}
          armBack={{ to: [28, 34], bend: [6, 22] }}
          armFront={{ to: [44, 30], bend: [32, -4] }}
          handFront="fist"
          holdFront={<Magnifier size={1.1} />}
        />

        {/* points the way on */}
        <Person
          x={880}
          y={318}
          s={1.45}
          lean={18}
          skin={SKIN.sky}
          top={C.lilac}
          bottom={C.coral}
          shoe={C.sky}
          hair={INK}
          hairStyle="band"
          band={C.sunshine}
          face="grin"
          legBack={{ to: [-22, 62], bend: [-16, 30] }}
          legFront={{ to: [32, 56], bend: [26, 20] }}
          armBack={{ to: [-42, 8], bend: [-30, -22] }}
          armFront={{ to: [70, -30], bend: [40, -2] }}
          handBack="open"
          handFront="point"
          handFrontScale={1.7}
        />
      </g>
    </svg>
  );
}

/** Noise to signal: catching a flurry of log pages, one of them flagged and set aside. */
export function NoiseScene({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 520 440" className={className} aria-hidden focusable="false">
      <Sheet x={96} y={70} w={52} rotate={-24} />
      <Sheet x={196} y={30} w={44} rotate={10} />
      <Sheet x={300} y={64} w={50} rotate={26} />
      <Sheet x={380} y={150} w={40} rotate={-8} mark="alert" />
      <Sheet x={60} y={190} w={38} rotate={18} />
      <path
        d="M392 162l28 28M420 162l-28 28"
        stroke={C.coral}
        strokeWidth="7"
        strokeLinecap="round"
      />
      <Squiggle x={404} y={56} rotate={24} w={60} />
      <circle cx="170" cy="150" r="7" fill={C.sky} />
      <Person
        x={250}
        y={330}
        s={1.15}
        lean={-6}
        skin={SKIN.tan}
        top={C.sunshine}
        sleeve={C.white}
        bottom={C.sky}
        shoe={C.coral}
        hair={INK}
        hairStyle="pony"
        face="shout"
        legBack={{ to: [-34, 66], bend: [-30, 24] }}
        legFront={{ to: [40, 60], bend: [36, 18] }}
        armBack={{ to: [-30, -64], bend: [-40, -20] }}
        armFront={{ to: [36, -68], bend: [40, -18] }}
        handBack="open"
        handFront="open"
      />
    </svg>
  );
}

/** A severity you can check: stamping the page with the level the evidence supports. */
export function StampScene({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 520 440" className={className} aria-hidden focusable="false">
      {/* the page on the desk, with the four probability bars and the prediction-set bracket */}
      <path d="M190 344L470 316L500 396L214 428Z" fill={C.white} />
      <g transform="translate(232 404) rotate(-6)">
        <rect x="0" y="-16" width="22" height="16" rx="3" fill={C.sand} />
        <rect x="30" y="-48" width="22" height="48" rx="3" fill={C.sev2} />
        <rect x="60" y="-28" width="22" height="28" rx="3" fill={C.sand} />
        <rect x="90" y="-10" width="22" height="10" rx="3" fill={C.sand} />
        <path
          d="M27 -60h58M27 -60v8M85 -60v8"
          fill="none"
          stroke={INK}
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <g transform="translate(410 372) rotate(-8)">
        <rect
          x="-36"
          y="-21"
          width="72"
          height="42"
          rx="8"
          fill="none"
          stroke={C.sev2}
          strokeWidth="5"
        />
        <text
          x="0"
          y="8"
          textAnchor="middle"
          fontSize="23"
          fontWeight="500"
          fill="#b35d09"
          fontFamily="Inter, ui-sans-serif, system-ui, sans-serif"
        >
          SEV2
        </text>
      </g>
      {/* the stamp just lifted off the page */}
      <path
        d="M390 312q8 -8 16 0M418 306q8 -8 16 0M446 312q8 -8 16 0"
        fill="none"
        stroke={INK}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <g transform="translate(418 214)">
        <Stamp size={1.2} />
      </g>
      <Squiggle x={70} y={70} rotate={-16} color={C.lilac} />
      <circle cx="470" cy="80" r="8" fill={C.sky} />
      <circle cx="80" cy="360" r="6" fill={C.sunshine} />
      <Person
        x={236}
        y={276}
        s={1.1}
        lean={22}
        skin={SKIN.deep}
        top={C.coral}
        bottom={C.lilac}
        shoe={C.sky}
        hair={INK}
        hairStyle="short"
        face="grin"
        legBack={{ to: [-28, 66], bend: [-24, 30] }}
        legFront={{ to: [22, 64], bend: [22, 30] }}
        armBack={{ to: [130, -44], bend: [60, 4] }}
        armFront={{ to: [138, -52], bend: [70, -2] }}
        handBack="fist"
        handFront="fist"
      />
    </svg>
  );
}

/** Every claim shows its evidence: a closer look at pinned pages joined by thread. */
export function EvidenceScene({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 520 440" className={className} aria-hidden focusable="false">
      <rect x="250" y="40" width="240" height="210" rx="10" fill={C.sand} />
      <Sheet x={270} y={60} w={58} rotate={-6} lines={3} />
      <Sheet x={398} y={70} w={58} rotate={7} lines={3} />
      <Sheet x={330} y={150} w={58} rotate={-3} lines={2} mark="tick" />
      <path d="M300 70L428 80M300 70L360 160M428 80L360 160" stroke={C.coral} strokeWidth="2.5" />
      <circle cx="300" cy="70" r="7" fill={C.coral} />
      <circle cx="428" cy="80" r="7" fill={C.coral} />
      <circle cx="360" cy="160" r="7" fill={C.coral} />
      <Squiggle x={70} y={90} rotate={-10} />
      <circle cx="120" cy="60" r="7" fill={C.sky} />
      <Person
        x={170}
        y={300}
        s={1.15}
        lean={10}
        skin={SKIN.peach}
        top={C.sky}
        bottom={INK}
        shoe={C.sunshine}
        hair="#6b3b22"
        hairStyle="puffs"
        face="focus"
        legBack={{ to: [-24, 66], bend: [-20, 30] }}
        legFront={{ to: [28, 64], bend: [22, 30] }}
        armBack={{ to: [30, 18], bend: [10, 28] }}
        armFront={{ to: [70, -46], bend: [40, -4] }}
        handFront="fist"
        holdFront={<Magnifier size={1.5} />}
      />
    </svg>
  );
}

/** Nothing goes out without you: a thumbs-up, and only then does the message fly. */
// The approved message's flight path: a cubic from the laptop up to the top right.
const FLIGHT: [number, number][] = [
  [312, 236],
  [356, 196],
  [384, 150],
  [436, 118],
];

function along(u: number): { x: number; y: number; angle: number } {
  const [p0, p1, p2, p3] = FLIGHT as [
    [number, number],
    [number, number],
    [number, number],
    [number, number],
  ];
  const v = 1 - u;
  const at = (i: 0 | 1) =>
    v * v * v * p0[i] + 3 * v * v * u * p1[i] + 3 * v * u * u * p2[i] + u * u * u * p3[i];
  const slope = (i: 0 | 1) =>
    3 * v * v * (p1[i] - p0[i]) + 6 * v * u * (p2[i] - p1[i]) + 3 * u * u * (p3[i] - p2[i]);
  return { x: at(0), y: at(1), angle: (Math.atan2(slope(1), slope(0)) * 180) / Math.PI };
}

export function ApproveScene({ className, planeAt }: { className?: string; planeAt?: number }) {
  // `planeAt` (0 to 1) is for the video: the message flies along its path once approved.
  const flight = planeAt == null ? null : along(Math.min(1, Math.max(0, planeAt)));
  return (
    <svg viewBox="0 0 520 440" className={className} aria-hidden focusable="false">
      <path
        d="M312 236C356 196 384 150 436 118"
        fill="none"
        stroke={INK}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray="2 12"
      />
      {flight ? (
        <PaperPlane x={flight.x - 20} y={flight.y - 26} w={74} rotate={flight.angle} />
      ) : (
        <PaperPlane x={428} y={92} w={74} rotate={-28} />
      )}
      <Cloud x={330} y={24} w={130} />
      <Squiggle x={70} y={110} rotate={14} color={C.coral} w={60} />
      <circle cx="470" cy="220" r="8" fill={C.sunshine} />
      <circle cx="110" cy="250" r="6" fill={C.sky} />
      <Person
        x={196}
        y={350}
        s={1.2}
        lean={-6}
        skin={SKIN.lilac}
        top={C.grass}
        bottom={C.sunshine}
        shoe={C.coral}
        hair={INK}
        hairStyle="bun"
        face="smile"
        legBack={{ to: [74, 2], bend: [40, -30] }}
        legFront={{ to: [70, 10], bend: [34, -40] }}
        armBack={{ to: [44, 6], bend: [20, 22] }}
        armFront={{ to: [16, -72], bend: [44, -30] }}
        handFront="thumb"
      />
      {/* the laptop on their knees, lid towards us, ARIA's mark on it */}
      <g transform="translate(262 316) rotate(-4)">
        <rect x="-4" y="-78" width="74" height="76" rx="7" fill={INK} transform="skewX(-10)" />
        <circle cx="24" cy="-40" r="13" fill={C.grass} />
        <circle cx="21" cy="-38.5" r="4.6" fill="none" stroke={INK} strokeWidth="2.6" />
        <path d="M26.5 -45v10" stroke={INK} strokeWidth="2.6" strokeLinecap="round" />
        <path d="M-10 -2H86L80 6H-6Z" fill={C.sand} />
      </g>
    </svg>
  );
}

function Flower({
  x,
  y,
  petals,
  centre,
  h = 70,
  r = 16,
}: {
  x: number;
  y: number;
  petals: string;
  centre: string;
  h?: number;
  r?: number;
}) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <path
        d={`M0 0Q-4 ${-h / 2} 0 ${-h}`}
        fill="none"
        stroke={C.grassDark}
        strokeWidth="5"
        strokeLinecap="round"
      />
      <path d={`M0 ${-h * 0.35}q14 -14 24 -6q-12 10 -24 6Z`} fill={C.grassDark} />
      <g transform={`translate(0 ${-h})`}>
        {[0, 60, 120, 180, 240, 300].map((a) => (
          <ellipse
            key={a}
            cx="0"
            cy={-r * 0.9}
            rx={r * 0.55}
            ry={r * 0.9}
            fill={petals}
            transform={`rotate(${a})`}
          />
        ))}
        <circle r={r * 0.55} fill={centre} />
      </g>
    </g>
  );
}

/** Bushes and flowers along the top of the closing green panel; the band ends in solid grass. */
export function HillsBand({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 1440 220"
      preserveAspectRatio="xMidYMax slice"
      className={className}
      aria-hidden
      focusable="false"
    >
      <path
        d="M0 120Q40 70 90 100Q130 50 190 92Q240 40 300 88Q350 56 400 96Q450 46 520 90Q580 60 630 98Q690 40 760 92Q820 56 870 96Q930 44 1000 90Q1060 58 1110 98Q1170 46 1240 92Q1300 60 1350 98Q1400 66 1440 96V220H0Z"
        fill={C.grassDeep}
      />
      <Flower x={150} y={150} petals={C.lilac} centre={C.sunshine} h={86} r={18} />
      <Flower x={470} y={150} petals={C.white} centre={C.coral} h={70} r={14} />
      <Flower x={820} y={150} petals={C.coral} centre={C.lilac} h={92} r={19} />
      <Flower x={1130} y={150} petals={C.sunshine} centre={C.sky} h={78} r={16} />
      <Flower x={1340} y={150} petals={C.sky} centre={C.white} h={64} r={13} />
      <path
        d="M0 170Q60 132 120 160Q180 120 250 156Q320 126 380 160Q450 122 520 158Q590 128 650 162Q720 124 790 158Q860 128 920 160Q990 122 1060 158Q1130 128 1190 162Q1260 124 1330 158Q1390 132 1440 156V220H0Z"
        fill={C.grass}
      />
    </svg>
  );
}
