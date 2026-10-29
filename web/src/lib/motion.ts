"use client";

import type { gsap } from "gsap";
import type { ScrollTrigger } from "gsap/ScrollTrigger";
import { useEffect, useEffectEvent, type RefObject } from "react";

/** Where the landing page animates: wide screens whose visitors have not asked for less motion. */
export const WIDE_MOTION = "(min-width: 1024px) and (prefers-reduced-motion: no-preference)";

export interface MotionTools {
  gsap: typeof gsap;
  ScrollTrigger: typeof ScrollTrigger;
}

/**
 * Run a GSAP setup while the screen matches {@link WIDE_MOTION}. GSAP loads only then, so phones
 * and reduced-motion visitors never download it. The setup runs inside a GSAP context scoped to
 * `scope`, and is reverted (with any cleanup it returns) when the screen stops matching or the
 * component unmounts.
 */
export function useWideMotion(
  scope: RefObject<HTMLElement | null>,
  setup: (tools: MotionTools) => void | (() => void),
): void {
  const run = useEffectEvent(setup);

  useEffect(() => {
    const media = window.matchMedia(WIDE_MOTION);
    let context: { revert: () => void } | undefined;
    let disposed = false;

    const start = async () => {
      const [core, scroll] = await Promise.all([import("gsap"), import("gsap/ScrollTrigger")]);
      if (disposed || context || !media.matches) return;
      core.gsap.registerPlugin(scroll.ScrollTrigger);
      context = core.gsap.context(
        () => run({ gsap: core.gsap, ScrollTrigger: scroll.ScrollTrigger }),
        scope.current ?? undefined,
      );
    };
    const stop = () => {
      context?.revert();
      context = undefined;
    };
    const onChange = () => {
      if (media.matches) void start();
      else stop();
    };

    onChange();
    media.addEventListener("change", onChange);
    return () => {
      disposed = true;
      media.removeEventListener("change", onChange);
      stop();
    };
  }, [scope]);
}
