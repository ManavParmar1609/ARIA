import { expect, expectAccessible, test } from "./fixtures";

// The public demo's shape (deploy/demo/Dockerfile): no API key, each visitor sees only the
// incidents they started plus the examples the server triaged at start, and nobody may change an
// example. Every test opens a fresh browser, so every test is a new visitor.

test.describe.configure({ mode: "serial" });

test.describe("public demo", () => {
  test("keeps each visitor's incidents to that visitor", async ({ page, browser }) => {
    await page.goto("/console/runs");
    const table = page.getByRole("table");
    // One approved example and one waiting for review, both marked, and neither counted as
    // waiting for this visitor's review.
    await expect(table.getByText("Example", { exact: true })).toHaveCount(2);
    await expect(page.getByText(/waiting for your review/)).toHaveCount(0);

    await page.goto("/console/runs/new?source=bigdata");
    await page
      .getByRole("button", { name: "Run it: Coordination servers lose touch with each other" })
      .click();
    await expect(page).toHaveURL(/\/console\/runs\/run-/);
    await expect(page.getByRole("heading", { name: "Waiting for your review" })).toBeVisible();
    const mine = new URL(page.url()).pathname;
    await page.goto("/console/runs");
    await expect(table.getByRole("link")).toHaveCount(3);
    await expect(page.getByText("1 incident is waiting for your review.")).toBeVisible();

    // Another visitor, in another browser: the examples, and nothing of the first visitor's.
    const elsewhere = await browser.newContext();
    try {
      const stranger = await elsewhere.newPage();
      await stranger.goto("/console/runs");
      await expect(stranger.getByRole("table").getByText("Example", { exact: true })).toHaveCount(
        2,
      );
      await expect(stranger.getByRole("table").getByRole("link")).toHaveCount(2);
      await stranger.goto(mine);
      await expect(stranger.getByText("This incident is not here")).toBeVisible();
      // Nothing waits for this visitor: the example that waits for review is not theirs.
      await expect(stranger.getByRole("link", { name: /waiting for review/ })).toHaveCount(0);
      await expect(stranger.getByText(/someone else's browser/)).toBeVisible();
    } finally {
      await elsewhere.close();
    }
  });

  test("makes a copy of an example to review", async ({ page }) => {
    await page.goto("/console/runs?status=awaiting_review");
    await page
      .getByRole("table")
      .getByRole("link", { name: /Brute-force/i })
      .click();
    await expect(page.getByRole("heading", { name: "This is an example" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Waiting for your review" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Delete" })).toHaveCount(0);
    await expectAccessible(page, "an example waiting for review");

    const example = new URL(page.url()).pathname;
    await page.getByRole("button", { name: "Make my own copy" }).click();
    await expect(page).not.toHaveURL(new RegExp(`${example}$`));
    await expect(page.getByRole("heading", { name: "Waiting for your review" })).toBeVisible();
    await page.getByRole("button", { name: "Approve and publish" }).click();
    await expect(page.getByRole("heading", { name: "Published", exact: true })).toBeVisible();

    // The example still waits for the next visitor.
    await page.goto(example);
    await expect(page.getByRole("heading", { name: "This is an example" })).toBeVisible();
  });
});
