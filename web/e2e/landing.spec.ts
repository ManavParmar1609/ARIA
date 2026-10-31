import { expect, expectAccessible, expectNoSidewaysScroll, test } from "./fixtures";

test.describe("landing page", () => {
  test("shows the recorded run and lets a citation reveal its evidence", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Turn a wall of logs into a report you can check.",
    );
    // The hero's report waits for a person; nothing in it can be pressed.
    await expect(
      page.getByText("Waiting for a person to approve. Nothing has been sent."),
    ).toBeVisible();
    await expect(page.locator("#main video")).toHaveAttribute("preload", "none");
    const tag = page.getByRole("article", { name: /Triage tag/ });
    await expect(tag).toBeVisible();
    await tag.getByRole("button", { name: "E2", exact: true }).first().hover();
    await expect(page.locator("#replay-evidence")).toContainText("log template");
    await expect(page.getByText("Quarantined: reads like an instruction, not a log")).toBeVisible();
    await expect(page.getByRole("heading", { name: "What the tests show" })).toBeVisible();
  });

  test("opens a plain-English definition from a dotted term", async ({ page }) => {
    // Still frames, so axe never measures text mid-fade (the replay plays in as it scrolls past).
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await page.getByRole("button", { name: "safety floors" }).click();
    const card = page.locator("#term-safety-floor");
    await expect(card).toBeVisible();
    await expect(card).toContainText("lowest severity a dangerous pattern can get");
    await expectAccessible(page, "landing, definition open");
    await page.keyboard.press("Escape");
    await expect(card).toBeHidden();
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

  test("links the hero to real incidents and each result to its test", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Try it on real logs" }).click();
    await expect(page).toHaveURL(/\/console\/runs\/new\?source=bigdata$/);
    await expect(page.getByRole("button", { name: /^Replay it: / }).first()).toBeVisible();
    await page.goto("/#results");
    const results = page.locator("section#results");
    await expect(results.getByRole("heading", { name: "What the tests show" })).toBeVisible();
    await expect(results.getByRole("listitem")).toHaveCount(4);
    await expect(results.getByRole("link", { name: "Where it falls short" })).toBeVisible();
    await results.getByRole("link", { name: "The real cluster test" }).click();
    await expect(page).toHaveURL(/\/console\/evals#ev-real$/);
  });

  test("reaches every section from the menu on a phone", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/");
    await page.getByRole("button", { name: "Open the menu" }).click();
    const menu = page.getByRole("navigation", { name: "Menu" });
    await expect(menu).toBeVisible();
    await expectAccessible(page, "landing, menu open");
    await menu.getByRole("link", { name: "Results" }).click();
    await expect(page).toHaveURL(/#results$/);
    await expect(menu).toBeHidden();
    await expect(page.getByRole("heading", { name: "What the tests show" })).toBeInViewport();
  });

  test("shows final states under reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const tag = page.getByRole("article", { name: /Triage tag/ });
    await expect(tag).toBeVisible();
    await expect(tag.getByText("Waiting for a person to approve")).toBeVisible();
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
