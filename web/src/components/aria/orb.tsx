"use client";

import { useEffect, useRef } from "react";

import { cx } from "@/lib/cx";

/*
 * The bioluminescent data orb (DESIGN.md): points on a Fibonacci sphere, teal at the back, white at
 * the front and lavender at the rim, with a thin shell of drifting dust. It is decoration only, so
 * it is hidden from assistive technology. It starts after the page has loaded, draws only while it
 * is on screen and the tab is visible, and holds one still frame under reduced motion.
 */

type Rgb = readonly [number, number, number];

interface Palette {
  back: Rgb;
  mid: Rgb;
  front: Rgb;
  rim: Rgb;
  /** Opacity of the farthest and nearest points. */
  alpha: readonly [number, number];
  blend: GlobalCompositeOperation;
}

const NIGHT: Palette = {
  back: [0, 130, 124], // bioluminescent teal #00827c
  mid: [203, 255, 252], // aqua #cbfffc
  front: [255, 255, 255],
  rim: [250, 209, 255], // aurora lavender #fad1ff
  alpha: [0.14, 0.95],
  blend: "lighter",
};

const DAY: Palette = {
  back: [124, 190, 186],
  mid: [0, 130, 124],
  front: [0, 55, 52], // liquid kelp
  rim: [150, 70, 165],
  alpha: [0.18, 0.85],
  blend: "source-over",
};

const DEPTHS = 12;
const RIMS = 3;
/** The band index for flaring points, drawn last and brightest. */
const FLARE = DEPTHS * RIMS;
const TAU = Math.PI * 2;
const GOLDEN = Math.PI * (3 - Math.sqrt(5));

const mix = (a: Rgb, b: Rgb, t: number): Rgb => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
];

/** One fill style per depth band and rim band, plus one for flares: at most 37 per frame. */
function fills(p: Palette): string[] {
  const out: string[] = [];
  for (let d = 0; d < DEPTHS; d++) {
    const t = d / (DEPTHS - 1);
    const base = t < 0.6 ? mix(p.back, p.mid, t / 0.6) : mix(p.mid, p.front, (t - 0.6) / 0.4);
    const alpha = p.alpha[0] + (p.alpha[1] - p.alpha[0]) * t ** 1.4;
    for (let r = 0; r < RIMS; r++) {
      const [red, green, blue] = mix(base, p.rim, [0, 0.4, 0.85][r] ?? 0);
      out.push(
        `rgba(${Math.round(red)},${Math.round(green)},${Math.round(blue)},${alpha.toFixed(3)})`,
      );
    }
  }
  const [red, green, blue] = p.mid;
  out.push(`rgba(${red},${green},${blue},1)`);
  return out;
}

/** Points spread evenly over a unit sphere, plus a sparse outer shell of dust. */
function points(count: number) {
  const x = new Float32Array(count);
  const y = new Float32Array(count);
  const z = new Float32Array(count);
  const shell = new Float32Array(count);
  const seed = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const h = 1 - (i / (count - 1)) * 2;
    const ring = Math.sqrt(1 - h * h);
    const theta = GOLDEN * i;
    x[i] = Math.cos(theta) * ring;
    y[i] = h;
    z[i] = Math.sin(theta) * ring;
    // A deterministic hash, so the dust sits in the same places on every load.
    const s = Math.abs(Math.sin(i * 12.9898) * 43758.5453) % 1;
    seed[i] = s;
    shell[i] = s < 0.07 ? 1.08 + s * 3.4 : 1;
  }
  return { x, y, z, shell, seed, count };
}

function schedule(callback: () => void): () => void {
  if ("requestIdleCallback" in window) {
    const id = window.requestIdleCallback(callback, { timeout: 1500 });
    return () => window.cancelIdleCallback(id);
  }
  const id = setTimeout(callback, 300);
  return () => clearTimeout(id);
}

export function Orb({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const root = document.documentElement;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    const finePointer = window.matchMedia("(pointer: fine)");

    let palette = fills(root.classList.contains("dark") ? NIGHT : DAY);
    let blend = root.classList.contains("dark") ? NIGHT.blend : DAY.blend;
    let width = 0;
    let height = 0;
    let dpr = 1;
    let cloud = points(0);
    let px = new Float32Array(0);
    let py = new Float32Array(0);
    let pr = new Float32Array(0);
    let band = new Uint8Array(0);
    // Points sorted by band each frame (a counting sort), so each band is one path and one fill.
    let order = new Uint16Array(0);
    const counts = new Uint16Array(FLARE + 2);
    // Touch screens get fewer points, fewer pixels and half the frame rate: the orb is decoration,
    // and a phone's processor and battery are for the page.
    const light = !finePointer.matches;

    let frame = 0;
    let started = false;
    let onScreen = true;
    let clock = 0;
    let last = 0;
    // The pointer tilts the orb a little; the tilt eases towards it.
    let aimX = 0;
    let aimY = 0;
    let tiltX = 0;
    let tiltY = 0;

    const resize = () => {
      const box = canvas.getBoundingClientRect();
      dpr = light ? 1 : Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(1, Math.round(box.width * dpr));
      height = Math.max(1, Math.round(box.height * dpr));
      canvas.width = width;
      canvas.height = height;
      const area = box.width * box.height;
      const count = Math.round(Math.min(light ? 1100 : 3600, Math.max(600, area / 120)));
      if (count !== cloud.count) {
        cloud = points(count);
        px = new Float32Array(count);
        py = new Float32Array(count);
        pr = new Float32Array(count);
        band = new Uint8Array(count);
        order = new Uint16Array(count);
      }
    };

    const draw = (t: number) => {
      const { x, y, z, shell, seed, count } = cloud;
      const radius = Math.min(width, height) * 0.36;
      const dot = Math.min(1.3, Math.max(0.7, radius / dpr / 250)) * dpr;
      const cx = width / 2;
      const cy = height / 2;
      const spin = t * 0.07 + tiltX * 0.5;
      const tilt = -0.38 + tiltY * 0.25;
      const cs = Math.cos(spin);
      const ss = Math.sin(spin);
      const ct = Math.cos(tilt);
      const st = Math.sin(tilt);

      for (let i = 0; i < count; i++) {
        const s = seed[i] ?? 0;
        const out = shell[i] ?? 1;
        // Dust drifts a little faster than the sphere; every point breathes on its own phase.
        const drift = out > 1 ? t * 0.05 : 0;
        const cd = Math.cos(drift);
        const sd = Math.sin(drift);
        const breathe = 1 + 0.03 * Math.sin(t * 0.9 + s * TAU);
        const r0 = out * breathe;
        const x0 = (x[i] ?? 0) * cd + (z[i] ?? 0) * sd;
        const z0 = (z[i] ?? 0) * cd - (x[i] ?? 0) * sd;
        const x1 = (x0 * cs + z0 * ss) * r0;
        const z1 = (z0 * cs - x0 * ss) * r0;
        const y1 = (y[i] ?? 0) * r0;
        const y2 = y1 * ct - z1 * st;
        const z2 = y1 * st + z1 * ct;
        const scale = 4 / (4 - z2);
        px[i] = cx + x1 * radius * scale;
        py[i] = cy + y2 * radius * scale;
        const depth = Math.min(1, Math.max(0, (z2 / out + 1) / 2));
        const rim = out > 1 ? 0 : 1 - Math.abs(z2);
        pr[i] = (0.35 + 1.05 * depth) * dot * (out > 1 ? 0.8 : 1);
        // A few points on the near side flare for a moment, like data arriving.
        if (depth > 0.45 && Math.sin(t * 1.3 + s * 97) > 0.992) {
          pr[i] = (pr[i] ?? 1) * 1.9;
          band[i] = FLARE;
          continue;
        }
        const d = Math.min(DEPTHS - 1, Math.floor(depth * DEPTHS));
        const r = rim > 0.86 ? 2 : rim > 0.66 ? 1 : 0;
        band[i] = d * RIMS + r;
      }

      counts.fill(0);
      for (let i = 0; i < count; i++)
        counts[(band[i] ?? 0) + 1] = (counts[(band[i] ?? 0) + 1] ?? 0) + 1;
      for (let b = 1; b < counts.length; b++) counts[b] = (counts[b] ?? 0) + (counts[b - 1] ?? 0);
      // counts[b] is now where band b starts; filling advances it to where band b ends.
      for (let i = 0; i < count; i++) {
        const b = band[i] ?? 0;
        order[counts[b] ?? 0] = i;
        counts[b] = (counts[b] ?? 0) + 1;
      }

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, width, height);
      ctx.globalCompositeOperation = blend;
      let start = 0;
      for (let b = 0; b < palette.length; b++) {
        const end = counts[b] ?? start;
        if (end > start) {
          ctx.beginPath();
          for (let k = start; k < end; k++) {
            const i = order[k] ?? 0;
            const x0 = px[i] ?? 0;
            const y0 = py[i] ?? 0;
            const r = pr[i] ?? 1;
            // Small dots are squares (far cheaper to fill, and a square of a pixel or two reads
            // as a dot); only the near, larger ones are drawn round.
            if (r < 1.6) ctx.rect(x0 - r, y0 - r, r * 2, r * 2);
            else {
              ctx.moveTo(x0 + r, y0);
              ctx.arc(x0, y0, r, 0, TAU);
            }
          }
          ctx.fillStyle = palette[b] ?? "transparent";
          ctx.fill();
        }
        start = end;
      }
    };

    const tick = (now: number) => {
      frame = 0;
      if (light && last && now - last < 30) {
        loop();
        return;
      }
      const step = last ? Math.min(0.05, (now - last) / 1000) : 0;
      last = now;
      clock += step;
      tiltX += (aimX - tiltX) * Math.min(1, step * 2.5);
      tiltY += (aimY - tiltY) * Math.min(1, step * 2.5);
      draw(clock);
      loop();
    };

    const loop = () => {
      if (frame || !started || still.matches || !onScreen || document.hidden) return;
      frame = requestAnimationFrame(tick);
    };

    const halt = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      last = 0;
    };

    const repaint = () => {
      if (!started) return;
      if (still.matches) draw(clock);
      else loop();
    };

    const onPointer = (event: PointerEvent) => {
      aimX = (event.clientX / window.innerWidth) * 2 - 1;
      aimY = (event.clientY / window.innerHeight) * 2 - 1;
    };

    const onTheme = () => {
      const dark = root.classList.contains("dark");
      palette = fills(dark ? NIGHT : DAY);
      blend = dark ? NIGHT.blend : DAY.blend;
      if (started) draw(clock);
    };

    const onMotion = () => {
      if (still.matches) {
        halt();
        draw(clock);
      } else loop();
    };

    const onVisibility = () => {
      if (document.hidden) halt();
      else loop();
    };

    // Sizing waits for the start too: allocating the canvas is work the first paint never needs.
    const sized = new ResizeObserver(() => {
      if (!started) return;
      resize();
      draw(clock);
    });
    const seen = new IntersectionObserver(([entry]) => {
      onScreen = entry?.isIntersecting ?? true;
      if (onScreen) loop();
      else halt();
    });
    const themed = new MutationObserver(onTheme);

    // Starting is split across an idle callback and a frame, so neither is a long task.
    const begin = () => {
      resize();
      frame = requestAnimationFrame(() => {
        frame = 0;
        started = true;
        draw(clock);
        canvas.dataset.ready = "";
        loop();
      });
    };

    let cancel = () => {};
    // Phones wait a little longer after load, so the page settles before the orb starts.
    const afterLoad = () => {
      if (!light) {
        cancel = schedule(begin);
        return;
      }
      const wait = setTimeout(() => {
        cancel = schedule(begin);
      }, 1200);
      cancel = () => clearTimeout(wait);
    };
    if (document.readyState === "complete") afterLoad();
    else window.addEventListener("load", afterLoad, { once: true });

    sized.observe(canvas);
    seen.observe(canvas);
    themed.observe(root, { attributes: true, attributeFilter: ["class"] });
    still.addEventListener("change", onMotion);
    document.addEventListener("visibilitychange", onVisibility);
    if (finePointer.matches) window.addEventListener("pointermove", onPointer, { passive: true });
    window.addEventListener("pageshow", repaint);

    return () => {
      cancel();
      halt();
      window.removeEventListener("load", afterLoad);
      sized.disconnect();
      seen.disconnect();
      themed.disconnect();
      still.removeEventListener("change", onMotion);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pointermove", onPointer);
      window.removeEventListener("pageshow", repaint);
    };
  }, []);

  return (
    <div aria-hidden className={cx("pointer-events-none select-none", className)}>
      {/* the glow is CSS, so the orb's light is there on first paint, before any script runs */}
      <div className="absolute inset-[14%] rounded-full bg-[radial-gradient(closest-side,var(--orb-glow),transparent)]" />
      <canvas
        ref={canvasRef}
        className="absolute inset-0 size-full opacity-0 transition-opacity duration-[1.6s] ease-(--ease-out) data-ready:opacity-100"
      />
    </div>
  );
}
