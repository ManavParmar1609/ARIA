import { Easing, interpolate } from "remotion";

const OUT = Easing.bezier(0.16, 1, 0.3, 1);

/** 0 to 1 over [start, start + duration] frames, eased out and clamped. */
export const progress = (frame: number, start: number, duration: number): number =>
  interpolate(frame, [start, start + duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: OUT,
  });

/** Opacity and a short rise for an element that enters at ``start``. */
export const enter = (frame: number, start: number, distance = 24) => {
  const p = progress(frame, start, 18);
  return { opacity: p, translate: `0px ${(1 - p) * distance}px` };
};
