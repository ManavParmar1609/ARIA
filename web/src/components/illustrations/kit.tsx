import { type ReactNode } from "react";

/*
 * A small kit for ARIA's storybook illustrations (DESIGN.md): flat fills from the palette, limbs
 * drawn as thick round-capped curves, and thin ink lines for fingers, faces and folds. No
 * outlines around shapes, no gradients, no shadows. Everything is computed at build time, so a
 * scene costs only its SVG markup.
 */

export const INK = "#2c2e2a";
export const C = {
  sev2: "#ffa659",
  grass: "#8ed462",
  grassDeep: "#6fbf3f",
  grassDark: "#57a62f",
  sky: "#2ba0ff",
  coral: "#ff705d",
  sunshine: "#f5e211",
  lilac: "#ebc0ff",
  sand: "#e0dbce",
  cream: "#f5f1e4",
  white: "#ffffff",
  ink: INK,
} as const;

export const SKIN = {
  peach: "#f8b996",
  tan: "#e3a072",
  brown: "#8a4b2c",
  deep: "#5e3521",
  sky: "#2ba0ff",
  lilac: "#dfb0fb",
} as const;

export type Pt = readonly [number, number];

const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;
export function rot([x, y]: Pt, d: number): Pt {
  const a = rad(d);
  return [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)];
}
export const add = (a: Pt, b: Pt): Pt => [a[0] + b[0], a[1] + b[1]];
const r1 = (n: number) => Math.round(n * 10) / 10;
export const p = (q: Pt) => `${r1(q[0])} ${r1(q[1])}`;
const angle = (from: Pt, to: Pt) => deg(Math.atan2(to[1] - from[1], to[0] - from[0]));

/** A limb from its joint: where the hand or foot ends up, and where the curve bends through. */
export interface Limb {
  to: Pt;
  bend: Pt;
}

type Hand = "mitt" | "point" | "open" | "fist" | "thumb" | "none";
type HairStyle = "bun" | "curly" | "short" | "pony" | "band" | "puffs";
type Face = "grin" | "smile" | "calm" | "shout" | "focus";

export interface PersonProps {
  x: number;
  y: number;
  /** Scale; 1 is about 190 units from shoe to crown. */
  s?: number;
  /** Mirror to face left. */
  flip?: boolean;
  /** Torso tilt in degrees; positive leans forward (towards where the person faces). */
  lean?: number;
  skin: string;
  top: string;
  sleeve?: string;
  bottom: string;
  shoe: string;
  hair: string;
  hairStyle: HairStyle;
  band?: string;
  face?: Face;
  armBack: Limb;
  armFront: Limb;
  legBack: Limb;
  legFront: Limb;
  handBack?: Hand;
  handFront?: Hand;
  /** Draw the front hand bigger, the reference's oversized pointing hand. */
  handFrontScale?: number;
  /** Drawn at the front hand, in a frame aligned with the forearm. */
  holdFront?: ReactNode;
  /** Drawn at the back hand. */
  holdBack?: ReactNode;
  /** Drawn over the torso (a print, a pocket, a lanyard). */
  print?: ReactNode;
}

const SHOULDER_BACK: Pt = [-15, -64];
const SHOULDER_FRONT: Pt = [15, -64];
const HIP_BACK: Pt = [-10, -6];
const HIP_FRONT: Pt = [10, -6];
const HEAD: Pt = [0, -104];

function limbPath(from: Pt, limb: Limb) {
  const bend = add(from, limb.bend);
  const end = add(from, limb.to);
  return { d: `M${p(from)}Q${p(bend)} ${p(end)}`, end, tangent: angle(bend, end) };
}

function HandShape({ at, dir, kind, skin }: { at: Pt; dir: number; kind: Hand; skin: string }) {
  if (kind === "none") return null;
  const t = `translate(${p(at)}) rotate(${r1(dir)})`;
  if (kind === "point") {
    // a big pointing hand: palm, index finger along the arm, thumb, and folded fingers in ink
    return (
      <g transform={t}>
        <ellipse cx="6" cy="0" rx="17" ry="14" fill={skin} />
        <rect x="10" y="-15" width="30" height="10" rx="5" fill={skin} />
        <ellipse cx="4" cy="-13" rx="8" ry="6" fill={skin} />
        <path
          d="M8 1q7 2 14 0M7 7q6 2 12 0M15 -5q4 0 8 2"
          fill="none"
          stroke={INK}
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </g>
    );
  }
  if (kind === "open") {
    return (
      <g transform={t}>
        <ellipse cx="6" cy="0" rx="13" ry="11" fill={skin} />
        <path
          d="M12 -8l9 -3M14 -2l10 0M13 4l9 3"
          stroke={skin}
          strokeWidth="6"
          strokeLinecap="round"
        />
        <path d="M5 -3q4 1 7 0" fill="none" stroke={INK} strokeWidth="1.6" strokeLinecap="round" />
      </g>
    );
  }
  if (kind === "thumb") {
    // a thumbs-up: the fist continues the forearm and the thumb stands along it
    return (
      <g transform={t}>
        <ellipse cx="5" cy="2" rx="11" ry="10" fill={skin} />
        <rect x="4" y="-17" width="9" height="16" rx="4.5" fill={skin} />
        <path
          d="M9 0q4 2 1 5M11 5q3 2 0 4"
          fill="none"
          stroke={INK}
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </g>
    );
  }
  if (kind === "fist") {
    return (
      <g transform={t}>
        <ellipse cx="5" cy="0" rx="11" ry="10" fill={skin} />
        <path
          d="M8 -5q3 2 0 4M10 1q3 2 0 4"
          fill="none"
          stroke={INK}
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </g>
    );
  }
  return (
    <g transform={t}>
      <ellipse cx="5" cy="0" rx="11" ry="9.5" fill={skin} />
    </g>
  );
}

function Shoe({ at, color, tilt }: { at: Pt; color: string; tilt: number }) {
  return (
    <g transform={`translate(${p(at)}) rotate(${r1(tilt)})`}>
      <path d="M-9 -9Q2 -14 15 -5Q23 1 17 7L-11 7Q-15 -1 -9 -9Z" fill={color} />
      <path d="M-12 4L19 4Q21 9 16 11L-10 11Q-14 9 -12 4Z" fill={C.white} />
      <path d="M0 -10q3 6 0 10" fill="none" stroke={INK} strokeWidth="1.6" strokeLinecap="round" />
    </g>
  );
}

function Hair({ style, color, band }: { style: HairStyle; color: string; band?: string }) {
  const cap = (
    <path d="M-25 4C-29 -20 -12 -31 4 -28C17 -26 26 -16 24 -6C14 -14 1 -16 -9 -11C-16 -7 -21 -2 -25 4Z" />
  );
  switch (style) {
    case "bun":
      return (
        <g fill={color}>
          {cap}
          <circle cx="-16" cy="-24" r="11" />
        </g>
      );
    case "curly":
      return (
        <g fill={color}>
          <circle cx="-15" cy="-14" r="13" />
          <circle cx="-4" cy="-23" r="12" />
          <circle cx="10" cy="-22" r="11" />
          <circle cx="20" cy="-12" r="8" />
          <circle cx="-22" cy="1" r="10" />
        </g>
      );
    case "pony":
      return (
        <g fill={color}>
          <ellipse cx="-30" cy="8" rx="9" ry="18" transform="rotate(28 -30 8)" />
          {cap}
        </g>
      );
    case "band":
      return (
        <g>
          <g fill={color}>{cap}</g>
          <path
            d="M-23 -12Q0 -26 23 -12"
            fill="none"
            stroke={band ?? C.sunshine}
            strokeWidth="7"
            strokeLinecap="round"
          />
        </g>
      );
    case "puffs":
      return (
        <g fill={color}>
          {cap}
          <circle cx="-22" cy="-20" r="10" />
          <circle cx="12" cy="-28" r="10" />
        </g>
      );
    default:
      return <g fill={color}>{cap}</g>;
  }
}

function FaceShape({ kind }: { kind: Face }) {
  const eyes = (
    <path
      d="M2 -5q3 -4 6 0M13 -5q3 -4 6 0"
      fill="none"
      stroke={INK}
      strokeWidth="2"
      strokeLinecap="round"
    />
  );
  switch (kind) {
    case "grin":
      return (
        <g>
          {eyes}
          <path d="M4 5Q12 19 21 4Z" fill={INK} />
          <path d="M8 10Q12 14 17 9Q13 7 8 10Z" fill={C.coral} />
          <path d="M5 5L20 4L19 6.5L6 7.5Z" fill={C.white} />
        </g>
      );
    case "shout":
      return (
        <g>
          {eyes}
          <ellipse cx="13" cy="9" rx="5" ry="6.5" fill={INK} />
        </g>
      );
    case "focus":
      return (
        <g>
          <circle cx="6" cy="-4" r="2" fill={INK} />
          <circle cx="16" cy="-4" r="2" fill={INK} />
          <path d="M8 8q4 2 8 0" fill="none" stroke={INK} strokeWidth="2" strokeLinecap="round" />
        </g>
      );
    case "calm":
      return (
        <g>
          {eyes}
          <path d="M8 7q4 3 8 0" fill="none" stroke={INK} strokeWidth="2" strokeLinecap="round" />
        </g>
      );
    default:
      return (
        <g>
          {eyes}
          <path
            d="M5 5Q12 14 20 5"
            fill="none"
            stroke={INK}
            strokeWidth="2"
            strokeLinecap="round"
          />
        </g>
      );
  }
}

/** One of the cast: a bean torso, a round head, rubber-hose limbs. Origin at the hips. */
export function Person(props: PersonProps) {
  const {
    x,
    y,
    s = 1,
    flip = false,
    lean = 0,
    skin,
    top,
    sleeve = top,
    bottom,
    shoe,
    hair,
    hairStyle,
    band,
    face = "smile",
    handBack = "mitt",
    handFront = "mitt",
    handFrontScale = 1,
  } = props;
  const sb = rot(SHOULDER_BACK, lean);
  const sf = rot(SHOULDER_FRONT, lean);
  const head = rot(HEAD, lean);
  const armB = limbPath(sb, props.armBack);
  const armF = limbPath(sf, props.armFront);
  const legB = limbPath(HIP_BACK, props.legBack);
  const legF = limbPath(HIP_FRONT, props.legFront);
  const shoeTilt = (tangent: number) => tangent - 90;
  return (
    <g transform={`translate(${p([x, y])}) scale(${flip ? -s : s} ${s})`}>
      <path d={legB.d} fill="none" stroke={bottom} strokeWidth="22" strokeLinecap="round" />
      <Shoe at={legB.end} color={shoe} tilt={shoeTilt(legB.tangent)} />
      <path d={armB.d} fill="none" stroke={sleeve} strokeWidth="16" strokeLinecap="round" />
      <HandShape at={armB.end} dir={armB.tangent} kind={handBack} skin={skin} />
      {props.holdBack ? (
        <g transform={`translate(${p(armB.end)}) rotate(${r1(armB.tangent)})`}>{props.holdBack}</g>
      ) : null}
      <g transform={`rotate(${r1(lean)})`}>
        <path
          d="M-21 -2C-25 -30 -27 -52 -24 -66Q-21 -82 -6 -82L6 -82Q21 -82 24 -66C27 -52 25 -30 21 -2Q0 7 -21 -2Z"
          fill={top}
        />
        {props.print}
      </g>
      <path d={legF.d} fill="none" stroke={bottom} strokeWidth="22" strokeLinecap="round" />
      <Shoe at={legF.end} color={shoe} tilt={shoeTilt(legF.tangent)} />
      <g transform={`translate(${p(head)}) rotate(${r1(lean * 0.5)})`}>
        <rect x="-7" y="14" width="14" height="14" rx="5" fill={skin} />
        <circle r="24" fill={skin} />
        <Hair style={hairStyle} color={hair} band={band} />
        <FaceShape kind={face} />
      </g>
      <path d={armF.d} fill="none" stroke={sleeve} strokeWidth="16" strokeLinecap="round" />
      <g
        transform={
          handFrontScale === 1
            ? undefined
            : `translate(${p(armF.end)}) scale(${handFrontScale}) translate(${p([-armF.end[0], -armF.end[1]])})`
        }
      >
        <HandShape at={armF.end} dir={armF.tangent} kind={handFront} skin={skin} />
      </g>
      {props.holdFront ? (
        <g transform={`translate(${p(armF.end)}) rotate(${r1(armF.tangent)})`}>{props.holdFront}</g>
      ) : null}
    </g>
  );
}

/** A soft white cloud; `w` is its width. */
export function Cloud({
  x,
  y,
  w = 160,
  fill = C.white,
}: {
  x: number;
  y: number;
  w?: number;
  fill?: string;
}) {
  const k = w / 160;
  return (
    <path
      transform={`translate(${p([x, y])}) scale(${r1(k * 100) / 100})`}
      d="M8 40C-6 40 -4 22 12 22C12 6 34 0 44 12C50 -4 78 -6 86 12C98 2 122 8 120 26C138 22 150 34 140 40Z"
      fill={fill}
    />
  );
}

/** A wobbly line of colour, the reference's confetti squiggle. */
export function Squiggle({
  x,
  y,
  color = C.sunshine,
  w = 70,
  rotate = 0,
}: {
  x: number;
  y: number;
  color?: string;
  w?: number;
  rotate?: number;
}) {
  const k = w / 70;
  return (
    <path
      transform={`translate(${p([x, y])}) rotate(${rotate}) scale(${r1(k * 100) / 100})`}
      d="M0 10Q8 -4 16 8T32 8T48 8T64 6"
      fill="none"
      stroke={color}
      strokeWidth="8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  );
}

/** A sheet of paper with a folded corner and a few lines of log text. */
export function Sheet({
  x,
  y,
  w = 54,
  rotate = 0,
  lines = 3,
  mark,
}: {
  x: number;
  y: number;
  w?: number;
  rotate?: number;
  lines?: number;
  /** A small badge in the corner: an alert or a tick. */
  mark?: "alert" | "tick";
}) {
  const h = w * 1.3;
  const fold = w * 0.28;
  return (
    <g transform={`translate(${p([x, y])}) rotate(${rotate})`}>
      <path
        d={`M0 0L${r1(w - fold)} 0L${r1(w)} ${r1(fold)}L${r1(w)} ${r1(h)}L0 ${r1(h)}Z`}
        fill={C.white}
      />
      <path
        d={`M${r1(w - fold)} 0L${r1(w - fold)} ${r1(fold)}L${r1(w)} ${r1(fold)}Z`}
        fill={C.sand}
      />
      <path
        d={Array.from({ length: lines }, (_, i) => {
          const ly = r1(h * 0.34 + i * h * 0.17);
          const lw = r1(w * (i % 2 ? 0.52 : 0.68));
          return `M${r1(w * 0.16)} ${ly}h${lw}`;
        }).join("")}
        stroke={INK}
        strokeWidth={r1(Math.max(1.4, w / 34))}
        strokeLinecap="round"
      />
      {mark === "alert" ? (
        <g transform={`translate(${r1(w * 0.18)} ${r1(h * 0.08)})`}>
          <circle r={r1(w * 0.14)} cx={r1(w * 0.14)} cy={r1(w * 0.14)} fill={C.coral} />
          <path
            d={`M${r1(w * 0.14)} ${r1(w * 0.07)}v${r1(w * 0.09)}`}
            stroke={INK}
            strokeWidth={r1(w / 24)}
            strokeLinecap="round"
          />
        </g>
      ) : null}
      {mark === "tick" ? (
        <g transform={`translate(${r1(w * 0.18)} ${r1(h * 0.08)})`}>
          <circle r={r1(w * 0.14)} cx={r1(w * 0.14)} cy={r1(w * 0.14)} fill={C.grass} />
          <path
            d={`M${r1(w * 0.07)} ${r1(w * 0.14)}l${r1(w * 0.05)} ${r1(w * 0.05)}l${r1(w * 0.09)} -${r1(w * 0.1)}`}
            fill="none"
            stroke={INK}
            strokeWidth={r1(w / 26)}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      ) : null}
    </g>
  );
}

/** A magnifying glass, held by its handle at the origin, pointing along +x. */
export function Magnifier({ size = 1 }: { size?: number }) {
  return (
    <g transform={`scale(${size})`}>
      <path d="M0 0L22 0" stroke={C.coral} strokeWidth="9" strokeLinecap="round" />
      <circle
        cx="44"
        cy="0"
        r="22"
        fill={C.white}
        fillOpacity="0.55"
        stroke={INK}
        strokeWidth="6"
      />
      <path
        d="M34 -10q6 -5 13 -3"
        fill="none"
        stroke={C.white}
        strokeWidth="4"
        strokeLinecap="round"
      />
    </g>
  );
}

/** A clipboard with a ticked report, upright, its clip at the top centre. */
export function Clipboard({ size = 1 }: { size?: number }) {
  return (
    <g transform={`scale(${size})`}>
      <rect x="-22" y="0" width="44" height="58" rx="5" fill={C.sky} />
      <rect x="-16" y="7" width="32" height="45" rx="2" fill={C.white} />
      <rect x="-9" y="-4" width="18" height="9" rx="3" fill={INK} />
      <path
        d="M-9 20l5 5l11 -12"
        fill="none"
        stroke={C.grassDark}
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M-9 36h18M-9 43h12" stroke={INK} strokeWidth="2" strokeLinecap="round" />
    </g>
  );
}

/** A paper plane flying along +x, for a message that has been approved and sent. */
export function PaperPlane({
  x,
  y,
  w = 60,
  rotate = 0,
}: {
  x: number;
  y: number;
  w?: number;
  rotate?: number;
}) {
  const k = w / 60;
  return (
    <g transform={`translate(${p([x, y])}) rotate(${rotate}) scale(${r1(k * 100) / 100})`}>
      <path d="M0 14L60 0L22 22Z" fill={C.white} />
      <path d="M22 22L60 0L26 34Z" fill={C.sand} />
      <path d="M22 22L26 34" stroke={INK} strokeWidth="1.6" strokeLinecap="round" />
    </g>
  );
}

/** A laptop seen from the side and front, its screen glowing sky blue. */
export function Laptop({ x, y, w = 110 }: { x: number; y: number; w?: number }) {
  const k = w / 110;
  return (
    <g transform={`translate(${p([x, y])}) scale(${r1(k * 100) / 100})`}>
      <rect x="8" y="-62" width="94" height="62" rx="6" fill={INK} />
      <rect x="15" y="-55" width="80" height="48" rx="3" fill={C.sky} />
      <path
        d="M26 -40h40M26 -30h28M26 -20h34"
        stroke={C.white}
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path d="M0 0H110L104 9H6Z" fill={C.sand} />
    </g>
  );
}

/** A rubber stamp held by its knob at the origin, face down. */
export function Stamp({ size = 1 }: { size?: number }) {
  return (
    <g transform={`scale(${size})`}>
      <circle cx="0" cy="0" r="13" fill={C.coral} />
      <rect x="-6" y="8" width="12" height="26" rx="4" fill={C.sand} />
      <rect x="-26" y="32" width="52" height="14" rx="4" fill={INK} />
      <rect x="-28" y="44" width="56" height="7" rx="3" fill={C.sev2} />
    </g>
  );
}
