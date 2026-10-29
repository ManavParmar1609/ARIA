import { expect, expectAccessible, expectNoSidewaysScroll, test } from "./fixtures";

test.describe("landing page", () => {
  test("shows the recorded run and lets a citation reveal its evidence", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Incident triage that shows its work.",
    );
    const tag = page.getByRole("article", { name: /Triage tag/ });
    await expect(tag).toBeVisible();
    await tag.getByRole("button", { name: "E2", exact: true }).hover();
    await expect(page.locator("#replay-evidence")).toContainText("log template");
    await expect(page.getByText("Quarantined: reads like an instruction, not a log")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Measured, caveats included" })).toBeVisible();
  });

  test("opens a plain-English definition from a dotted term", async ({ page }) => {
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
    await expectAccessible(page, "landing, dark");
    await page.evaluate(() => {
      localStorage.setItem("theme", "light");
    });
    await page.reload();
    await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
    await expectAccessible(page, "landing, light");
  });

  test("switches theme and remembers it", async ({ page }) => {
    await page.goto("/");
    const html = page.locator("html");
    await expect(html).toHaveClass(/\bdark\b/);
    await page.getByRole("button", { name: "Use the light theme" }).click();
    await expect(html).not.toHaveClass(/\bdark\b/);
    await page.reload();
    await expect(html).not.toHaveClass(/\bdark\b/);
    await page.getByRole("button", { name: "Use the dark theme" }).click();
    await expect(html).toHaveClass(/\bdark\b/);
  });

  test("reflows to 320 px without sideways scrolling", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectNoSidewaysScroll(page, "landing");
  });

  test("shows final states under reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.getByRole("article", { name: /Triage tag/ })).toBeVisible();
    await expect(page.getByText("Waiting for a person to approve")).toBeVisible();
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
