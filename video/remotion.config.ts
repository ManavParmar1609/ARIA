// Remotion CLI settings (studio and render). See https://www.remotion.dev/docs/config
import path from "node:path";

import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(92);
Config.setOverwriteOutput(true);
Config.setCodec("h264");
Config.setPixelFormat("yuv420p");

// Remotion downloads its own headless Chrome. Where it cannot (an offline or locked-down
// machine), point this at a local Chrome Headless Shell instead.
const browser = process.env.REMOTION_BROWSER_EXECUTABLE;
if (browser) {
  Config.setBrowserExecutable(browser);
}

// The video draws the website's illustrations (web/src/components/illustrations), so the two never
// drift apart. Those files import React; resolve it from this package, so a render uses one copy.
Config.overrideWebpackConfig((config) => ({
  ...config,
  resolve: {
    ...config.resolve,
    alias: {
      ...(config.resolve?.alias as Record<string, string> | undefined),
      react: path.resolve("node_modules/react"),
      "react/jsx-runtime": path.resolve("node_modules/react/jsx-runtime.js"),
      "react/jsx-dev-runtime": path.resolve("node_modules/react/jsx-dev-runtime.js"),
    },
  },
}));
