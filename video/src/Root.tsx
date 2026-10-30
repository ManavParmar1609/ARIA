import { Composition } from "remotion";

import { AriaDemo, DURATION, FPS } from "./AriaDemo";

export const RemotionRoot = () => (
  <Composition
    id="AriaDemo"
    component={AriaDemo}
    durationInFrames={DURATION}
    fps={FPS}
    width={1920}
    height={1080}
  />
);
