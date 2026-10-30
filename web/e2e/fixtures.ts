import AxeBuilder from "@axe-core/playwright";
import { test as base, expect, type Page } from "@playwright/test";

/** Every test fails on a console error or an uncaught exception in the page. */
export const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      page.on("pageerror", (error) => errors.push(`uncaught: ${error.message}`));
      await use(errors);
      expect(errors, "console errors").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/** WCAG 2.2 A and AA checks with axe-core, on the page as it looks once still. Motion is reduced
 * while axe reads the page, so nothing is measured halfway through a fade: a toast that is
 * leaving would read as low-contrast text. The page's own setting comes back afterwards. */
export async function expectAccessible(page: Page, context?: string) {
  const reduced = await page.evaluate(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  await page.emulateMedia({ reducedMotion: "reduce" });
  try {
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    const summary = results.violations.map(
      (v) =>
        `${v.id} (${v.impact}): ${v.nodes
          .map((n) => n.target.join(" "))
          .slice(0, 3)
          .join(", ")}`,
    );
    expect(summary, `axe violations${context ? ` on ${context}` : ""}`).toEqual([]);
  } finally {
    if (!reduced) await page.emulateMedia({ reducedMotion: null });
  }
}

/** WCAG 1.4.10 reflow: the page must not scroll sideways at its current width. */
export async function expectNoSidewaysScroll(page: Page, context: string) {
  const [scroll, client] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  expect(scroll, `${context} scrolls sideways`).toBeLessThanOrEqual(client);
}
