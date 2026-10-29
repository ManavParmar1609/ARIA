import type { CSSProperties } from "react";
import { useMemo } from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";

/*
 * The bioluminescent data orb from the landing page (web/src/components/aria/orb.tsx), redrawn
 * for video: an SVG computed from the frame number, so every render of a frame is identical.
 * Points sit on a Fibonacci sphere, teal at the back, white at the front and lavender at the rim,
 * with a thin shell of drifting dust and the odd near point flaring like data arriving.
 */

type Rgb = readonly [number, number, number];

const TEAL: Rgb = [0, 130, 124];
const AQUA: Rgb = [203, 255, 252];
const WHITE: Rgb = [255, 255, 255];
const LAVENDER: Rgb = [250, 209, 255];
const GOLDEN = Math.PI * (3 - Math.sqrt(5));
const TAU = Math.PI * 2;

const mix = (a: Rgb, b: Rgb, t: number): Rgb => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
];

const rgb = ([r, g, b]: Rgb) => `rgb(${Math.round(r)},${Math.round(g)},${Math.round(b)})`;

interface Point {
  x: number;
  y: number;
  z: number;
  shell: number;
  seed: number;
}

function sphere(count: number): Point[] {
  return Array.from({ length: count }, (_, i) => {
    const h = 1 - (i / (count - 1)) * 2;
    const ring = Math.sqrt(1 - h * h);
    const theta = GOLDEN * i;
    const seed = Math.abs(Math.sin(i * 12.9898) * 43758.5453) % 1;
    return {
      x: Math.cos(theta) * ring,
      y: h,
      z: Math.sin(theta) * ring,
      seed,
      shell: seed < 0.07 ? 1.08 + seed * 3.4 : 1,
    };
  });
}

export const Orb = ({
  size,
  count = 1500,
  speed = 0.2,
  style,
}: {
  /** Width and height of the square it draws into, in pixels. */
  size: number;
  count?: number;
  /** Turns per second, in radians. */
  speed?: number;
  style?: CSSProperties;
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const points = useMemo(() => sphere(count), [count]);
  const t = frame / fps;
  const radius = size * 0.36;
  const centre = size / 2;
  const spin = t * speed;
  const tilt = -0.38;
  const [cs, ss, ct, st] = [Math.cos(spin), Math.sin(spin), Math.cos(tilt), Math.sin(tilt)];

  const dots = points
    .map((p) => {
      const drift = p.shell > 1 ? t * 0.08 : 0;
      const breathe = 1 + 0.03 * Math.sin(t * 0.9 + p.seed * TAU);
      const r0 = p.shell * breathe;
      const x0 = p.x * Math.cos(drift) + p.z * Math.sin(drift);
      const z0 = p.z * Math.cos(drift) - p.x * Math.sin(drift);
      const x1 = (x0 * cs + z0 * ss) * r0;
      const z1 = (z0 * cs - x0 * ss) * r0;
      const y1 = p.y * r0;
      const y2 = y1 * ct - z1 * st;
      const z2 = y1 * st + z1 * ct;
      const scale = 4 / (4 - z2);
      const depth = Math.min(1, Math.max(0, (z2 / p.shell + 1) / 2));
      const rim = p.shell > 1 ? 0 : 1 - Math.abs(z2);
      const flare = depth > 0.45 && Math.sin(t * 1.3 + p.seed * 97) > 0.992;
      const base =
        depth < 0.6 ? mix(TEAL, AQUA, depth / 0.6) : mix(AQUA, WHITE, (depth - 0.6) / 0.4);
      const tint = rim > 0.86 ? 0.85 : rim > 0.66 ? 0.4 : 0;
      return {
        x: centre + x1 * radius * scale,
        y: centre + y2 * radius * scale,
        z: z2,
        r: (0.7 + 2.1 * depth) * (size / 1000) * (p.shell > 1 ? 0.8 : 1) * (flare ? 1.9 : 1),
        fill: flare ? rgb(AQUA) : rgb(mix(base, LAVENDER, tint)),
        opacity: flare ? 1 : 0.14 + 0.81 * depth ** 1.4,
      };
    })
    .sort((a, b) => a.z - b.z);

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={style} aria-hidden>
      <defs>
        <radialGradient id="orb-glow">
          <stop offset="0%" stopColor="rgb(0, 130, 124)" stopOpacity={0.32} />
          <stop offset="100%" stopColor="rgb(0, 130, 124)" stopOpacity={0} />
        </radialGradient>
      </defs>
      <circle cx={centre} cy={centre} r={radius * 1.25} fill="url(#orb-glow)" />
      {dots.map((d, i) => (
        <circle key={i} cx={d.x} cy={d.y} r={d.r} fill={d.fill} opacity={d.opacity} />
      ))}
    </svg>
  );
};
