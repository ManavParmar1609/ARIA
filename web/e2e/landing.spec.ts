import { expect, expectAccessible, expectNoSidewaysScroll, test } from "./fixtures";

test.describe("landing page", () => {
  test("stays short: the headline, the proof, four steps and the way in", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Turn a wall of logs into a report you can check.",
    );
    // The hero's report waits for a person; nothing in it can be pressed.
    await expect(
      page.getByText("Waiting for a person to approve. Nothing has been sent."),
    ).toBeVisible();
    await expect(page.locator("main").getByRole("heading", { level: 2 })).toHaveText([
      "Tested on public, labelled logs",
      "Every claim cites a log line",
      "Nothing is sent without you",
      "How it works, in four steps",
      "Let ARIA take the first look.",
    ]);
    // About three screens on a laptop: the detail lives on How ARIA works.
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    expect(height).toBeLessThan(3 * 900);
    // The header's links stay on the site, so only the source carries an outbound arrow.
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.locator("svg")).toHaveCount(1);
    await nav.getByRole("link", { name: "How it works" }).click();
    await expect(page).toHaveURL(/\/console\/how-it-works$/);
    await expect(page.getByRole("heading", { level: 1, name: "How ARIA works" })).toBeVisible();
  });

  test("meets WCAG 2.2 AA in both themes", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
    await expectAccessible(page, "landing, light");
    await page.evaluate(() => {
      localStorage.setItem("theme", "dark");
    });
    await page.reload();
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await expectAccessible(page, "landing, dark");
  });

  test("switches theme and remembers it", async ({ page }) => {
    // On a wide screen the theme button sits in the header: the sections need no menu there.
    await page.goto("/");
    const html = page.locator("html");
    await expect(html).not.toHaveClass(/\bdark\b/);
    await expect(page.getByRole("button", { name: "Open the menu" })).toBeHidden();
    await page.getByRole("button", { name: "Use the dark theme" }).click();
    await expect(html).toHaveClass(/\bdark\b/);
    await page.reload();
    await expect(html).toHaveClass(/\bdark\b/);
    await page.getByRole("button", { name: "Use the light theme" }).click();
    await expect(html).not.toHaveClass(/\bdark\b/);
  });

  test("reflows to 320 px without sideways scrolling", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectNoSidewaysScroll(page, "landing");
  });

  test("links the hero to real incidents and each proof to its page", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "See an example" }).click();
    await expect(page).toHaveURL(/\/console\/how-it-works\/example$/);
    await expect(page.getByRole("article", { name: /Triage tag/ })).toBeVisible();
    await page.goto("/");
    await page.getByRole("link", { name: "Try it on real logs" }).click();
    // New triage as a first visit sees it: the real incident leads "Start with one of these".
    await expect(page).toHaveURL(/\/console\/runs\/new$/);
    await expect(page.getByRole("button", { name: /^Replay it: / }).first()).toBeVisible();
  });

  test("reaches every page it names from the menu on a phone", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/");
    await page.getByRole("button", { name: "Open the menu" }).click();
    const menu = page.getByRole("navigation", { name: "Menu" });
    await expect(menu).toBeVisible();
    await expectAccessible(page, "landing, menu open");
    await menu.getByRole("link", { name: "Questions" }).click();
    await expect(page).toHaveURL(/\/console\/how-it-works\/questions$/);
    await expect(page.getByRole("heading", { name: "What people ask first" })).toBeVisible();
  });

  test("serves llms.txt for agents", async ({ request }) => {
    const response = await request.get("/llms.txt");
    expect(response.ok()).toBe(true);
    expect(response.headers()["content-type"]).toContain("text/plain");
    const text = await response.text();
    expect(text.startsWith("# ARIA\n")).toBe(true);
    expect(text).toContain("semi-synthetic");
  });
});

test.describe("how ARIA works", () => {
  test("walks through its parts in order, one short page each", async ({ page }) => {
    await page.goto("/console/how-it-works");
    await expect(page.locator("main video")).toHaveAttribute("preload", "none");
    const parts = page.getByRole("navigation", { name: "Parts of How ARIA works" });
    await expect(parts.getByRole("link", { name: "What it does" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    for (const [name, path] of [
      ["An example", "example"],
      ["The four steps", "steps"],
      ["Test results", "results"],
      ["Questions", "questions"],
    ]) {
      await page.getByRole("link", { name: `Next: ${name}` }).click();
      await expect(page).toHaveURL(new RegExp(`/console/how-it-works/${path}$`));
      await expect(parts.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
    }
    // The last part leads to a triage of your own.
    await page.getByRole("link", { name: "Try it on real logs" }).click();
    await expect(page).toHaveURL(/\/console\/runs\/new$/);
  });

  test("lets a citation in the example reveal its evidence", async ({ page }) => {
    await page.goto("/console/how-it-works/example");
    const tag = page.getByRole("article", { name: /Triage tag/ });
    await expect(tag).toBeVisible();
    await tag.getByRole("button", { name: "E2", exact: true }).first().hover();
    await expect(page.locator("#replay-evidence")).toContainText("log template");
    await expect(page.getByText("Quarantined: reads like an instruction, not a log")).toBeVisible();
  });

  test("shows the example's final state under reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/console/how-it-works/example");
    const tag = page.getByRole("article", { name: /Triage tag/ });
    await expect(tag).toBeVisible();
    await expect(tag.getByText("Waiting for a person to approve")).toBeVisible();
  });

  test("opens a plain-English definition from a dotted term", async ({ page }) => {
    // Still frames, so axe never measures text mid-fade.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/console/how-it-works/steps");
    await page.getByRole("button", { name: "short list" }).click();
    const card = page.locator("#term-prediction-set");
    await expect(card).toBeVisible();
    await expect(card).toContainText("The levels ARIA cannot rule out");
    await expectAccessible(page, "how it works, definition open");
    await page.keyboard.press("Escape");
    await expect(card).toBeHidden();
  });

  test("links each result to its test", async ({ page }) => {
    await page.goto("/console/how-it-works/results");
    const results = page.locator("section", {
      has: page.getByRole("heading", { name: "What the tests show" }),
    });
    await expect(results.getByRole("listitem")).toHaveCount(3);
    await expect(results.getByRole("link", { name: "When it asks a person" })).toBeVisible();
    await expect(results.getByRole("link", { name: "The end-to-end test" })).toBeVisible();
    await results.getByRole("link", { name: "The real cluster test" }).click();
    await expect(page).toHaveURL(/\/console\/evals#ev-real$/);
  });

  test("meets WCAG 2.2 AA on every part, in both themes", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    for (const theme of ["light", "dark"]) {
      await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
      for (const part of ["", "/example", "/steps", "/results", "/questions"]) {
        await page.goto(`/console/how-it-works${part}`);
        await expect(page.getByRole("heading", { level: 1, name: "How ARIA works" })).toBeVisible();
        await expectAccessible(page, `how it works${part}, ${theme}`);
      }
    }
  });
});
