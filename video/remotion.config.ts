// Remotion CLI settings (studio and render). See https://www.remotion.dev/docs/config
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
