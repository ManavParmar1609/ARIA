import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { useVideoConfig } from "remotion";

import { FADE } from "./motion";
import { Close } from "./scenes/Close";
import { Intake } from "./scenes/Intake";
import { Investigate } from "./scenes/Investigate";
import { Measured } from "./scenes/Measured";
import { Opening } from "./scenes/Opening";
import { Parse } from "./scenes/Parse";
import { Report } from "./scenes/Report";
import { Review } from "./scenes/Review";
import { Severity } from "./scenes/Severity";

export const FPS = 30;
// Scene lengths in seconds; each fade overlaps two scenes by FADE frames.
const SCENES = [5, 9, 9, 14, 11, 13, 8, 13, 6];
export const DURATION = SCENES.reduce((sum, s) => sum + s * FPS, 0) - (SCENES.length - 1) * FADE;

export const AriaDemo = () => {
  const { fps } = useVideoConfig();
  const fadeTiming = linearTiming({ durationInFrames: FADE });
  return (
    <TransitionSeries>
      <TransitionSeries.Sequence name="Opening" durationInFrames={5 * fps}>
        <Opening />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />
      <TransitionSeries.Sequence name="Intake" durationInFrames={9 * fps}>
        <Intake />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />
      <TransitionSeries.Sequence name="Parse" durationInFrames={9 * fps}>
        <Parse />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />
      <TransitionSeries.Sequence name="Severity" durationInFrames={14 * fps}>
        <Severity />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />
      <TransitionSeries.Sequence name="Investigate" durationInFrames={11 * fps}>
        <Investigate />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />
      <TransitionSeries.Sequence name="Report" durationInFrames={13 * fps}>
        <Report />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />
      <TransitionSeries.Sequence name="Review" durationInFrames={8 * fps}>
        <Review />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />
      <TransitionSeries.Sequence name="Measured" durationInFrames={13 * fps}>
        <Measured />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />
      <TransitionSeries.Sequence name="Close" durationInFrames={6 * fps}>
        <Close />
      </TransitionSeries.Sequence>
    </TransitionSeries>
  );
};
