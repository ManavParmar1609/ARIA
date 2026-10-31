import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";

// End-to-end tests run the real stack: an offline ARIA API (fake LLM provider, fresh SQLite
// database seeded from the Loghub fixtures) and the production build of this app.
const API_PORT = Number(process.env.E2E_API_PORT ?? 8100);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3200);
const dataDir = fileURLToPath(new URL("./test-results/e2e-api", import.meta.url));
// A second stack shaped like the public demo (deploy/demo/Dockerfile): each visitor sees only
// their own incidents, plus examples the server triaged at start, which nobody can change.
const DEMO_API_PORT = API_PORT + 1;
const DEMO_WEB_PORT = WEB_PORT + 1;
const demoDir = fileURLToPath(new URL("./test-results/e2e-demo-api", import.meta.url));

// Offline and deterministic: never reach a hosted model, even if a key is exported.
const OFFLINE = {
  NVIDIA_API_KEY: "",
  GEMINI_API_KEY: "",
  gemini_api_key: "",
  AZURE_OPENAI_API_KEY: "",
  OPENAI_API_KEY: "",
  OPENAI_COMPAT_BASE_URL: "",
  ANTHROPIC_API_KEY: "",
  NIM_LOCAL_BASE_URL: "",
};

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined },
  },
  projects: [
    {
      name: "chromium",
      testIgnore: /demo\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "public demo",
      testMatch: /demo\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        baseURL: `http://127.0.0.1:${DEMO_WEB_PORT}`,
      },
    },
  ],
  webServer: [
    {
      // A fresh database each run: migrate, seed incident memory, then serve.
      command: `rm -rf "${dataDir}" && mkdir -p "${dataDir}" && uv run aria db upgrade && uv run aria seed --workers 2 && uv run aria serve --port ${API_PORT}`,
      cwd: "..",
      url: `http://127.0.0.1:${API_PORT}/healthz`,
      timeout: 240_000,
      reuseExistingServer: false,
      stdout: "ignore",
      stderr: "pipe",
      env: {
        ARIA_ENV: "test",
        ARIA_DATABASE_URL: `sqlite:///${dataDir}/aria.db`,
        ARIA_DATA_DIR: dataDir,
        ARIA_RATE_LIMIT_PER_MINUTE: "100000",
        ARIA_LOG_FORMAT: "console",
        UV_NO_PROGRESS: "1",
        // The Settings page shows the form for a visitor's own model key, so axe checks it. No
        // test sends a key.
        ARIA_VISITOR_KEYS: "true",
        ...OFFLINE,
      },
    },
    {
      command: `node node_modules/next/dist/bin/next start -p ${WEB_PORT}`,
      url: `http://127.0.0.1:${WEB_PORT}/`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { ARIA_API_URL: `http://127.0.0.1:${API_PORT}`, NEXT_TELEMETRY_DISABLED: "1" },
    },
    {
      // As the demo image builds it: memory, one approved example and one waiting for review.
      command: [
        `rm -rf "${demoDir}" && mkdir -p "${demoDir}"`,
        "uv run aria db upgrade",
        "uv run aria seed --workers 2",
        "uv run aria triage --scenario zookeeper.quorum_connection_loss --approve",
        "uv run aria triage --scenario openssh.bruteforce",
        `uv run aria serve --port ${DEMO_API_PORT}`,
      ].join(" && "),
      cwd: "..",
      url: `http://127.0.0.1:${DEMO_API_PORT}/healthz`,
      timeout: 300_000,
      reuseExistingServer: false,
      stdout: "ignore",
      stderr: "pipe",
      env: {
        ARIA_ENV: "test",
        ARIA_DATABASE_URL: `sqlite:///${demoDir}/aria.db`,
        ARIA_DATA_DIR: demoDir,
        ARIA_RATE_LIMIT_PER_MINUTE: "100000",
        ARIA_LOG_FORMAT: "console",
        ARIA_VISITOR_SCOPE: "true",
        UV_NO_PROGRESS: "1",
        ...OFFLINE,
      },
    },
    {
      command: `node node_modules/next/dist/bin/next start -p ${DEMO_WEB_PORT}`,
      url: `http://127.0.0.1:${DEMO_WEB_PORT}/`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { ARIA_API_URL: `http://127.0.0.1:${DEMO_API_PORT}`, NEXT_TELEMETRY_DISABLED: "1" },
    },
  ],
});
