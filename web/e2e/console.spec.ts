import { expect, expectAccessible, expectNoSidewaysScroll, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

test.describe("console", () => {
  test("triages a sample, follows it live, and publishes it after review", async ({ page }) => {
    await page.goto("/console");
    await expect(page.getByText("Nothing is waiting for review")).toBeVisible();
    await expectAccessible(page, "overview, empty");

    await page.getByRole("link", { name: "New triage" }).first().click();
    await page.getByRole("button", { name: /ZooKeeper quorum connection loss/ }).click();
    await expect(page.getByLabel("Log lines")).not.toBeEmpty();
    await expectAccessible(page, "new triage");
    await page.getByRole("button", { name: "Start triage" }).click();

    await expect(page).toHaveURL(/\/console\/runs\/run-/);
    await expect(page.getByRole("heading", { name: "Waiting for your review" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Severity", exact: true })).toBeVisible();
    await expect(page.getByText(/Validated: \d+ claims, 100% cited/)).toBeVisible();

    // hover-to-evidence: a citation in the report fills the evidence panel
    const citation = page
      .locator("article")
      .getByRole("button", { name: /^Evidence E\d+: Log template/ })
      .first();
    await citation.hover();
    await expect(page.locator("#evidence-panel")).toContainText("Log template");
    await expectAccessible(page, "run view, awaiting review");

    await page.getByRole("checkbox").first().check();
    await page.getByRole("button", { name: "Approve and send 1" }).click();
    await expect(page.getByText("Published", { exact: true }).first()).toBeVisible();
    await page.getByRole("tab", { name: "Agent activity" }).click();
    await expect(page.getByText(/Review: approve by/)).toBeVisible();
    await expect(page.getByText(/Run finished: published/)).toBeVisible();

    // time travel: view the run as it was before the review, then come back
    await page.getByRole("tab", { name: "History and forks" }).click();
    await page
      .locator("li", { hasText: "Paused before review" })
      .getByRole("button", { name: "View" })
      .click();
    await expect(page.getByText(/as it was at a past checkpoint/)).toBeVisible();
    await expect(
      page.getByText("Draft: nothing has been sent. A reviewer must approve it first."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Back to now" }).click();
    await expect(page.getByText(/as it was at a past checkpoint/)).toBeHidden();
  });

  test("lists the published run and opens its runbook", async ({ page }) => {
    await page.goto("/console/runs?status=published");
    const row = page.getByRole("row", { name: /ZooKeeper/ });
    await expect(row).toBeVisible();
    await expectAccessible(page, "incidents");
    await row.getByRole("link").click();
    await page
      .getByRole("link", { name: /zookeeper-quorum-loss/ })
      .first()
      .click();
    await expect(page.getByRole("heading", { name: "Mitigate" })).toBeVisible();
    await expectAccessible(page, "runbook");
  });

  test("searches incident memory by meaning", async ({ page }) => {
    await page.goto("/console/memory");
    await page.getByLabel("Search").fill("quorum lost between peers");
    await expect(page.getByText(/closest incidents to "quorum lost between peers"/)).toBeVisible();
    await expect(page.locator("details").first()).toContainText(/ZooKeeper/i);
    await expectAccessible(page, "memory");
  });

  test("answers a question with citations", async ({ page }) => {
    await page.goto("/console/ask");
    await page.getByLabel("Your question").fill("How was ZooKeeper quorum loss fixed before?");
    await page.getByRole("button", { name: "Ask ARIA" }).click();
    await expect(
      page
        .locator("ol li")
        .first()
        .getByRole("button", { name: /^Evidence E\d+/ })
        .first(),
    ).toBeVisible();
    await expectAccessible(page, "ask");
  });

  test("triages in chat over AG-UI and answers the review interrupt", async ({ page }) => {
    await page.goto("/console/ask");
    await page.getByRole("tab", { name: /Triage in chat/ }).click();
    await page.getByRole("button", { name: /Use the ssh brute-force attempts sample/i }).click();
    await page.getByRole("button", { name: "Triage in chat" }).click();
    await expect(page.getByText(/Review the incident report/)).toBeVisible();
    await expect(page.locator("li:has(svg.lucide-wrench)").first()).toBeVisible();
    await page.getByRole("button", { name: "Approve and publish" }).click();
    await expect(page.getByText(/Run published/)).toBeVisible();
  });

  test("shows evaluation, runbooks and settings", async ({ page }) => {
    for (const [path, heading] of [
      ["/console/evals", "Evaluation"],
      ["/console/runbooks", "Runbooks"],
      ["/console/settings", "Settings"],
    ] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await expectAccessible(page, path);
    }
    // The theme setting applies at once and survives a reload. The radios are styled labels
    // around visually hidden inputs, so click the label as a person would.
    const themeOption = (name: string) => page.locator("label").filter({ hasText: name });
    await themeOption("Light").click();
    await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
    await page.reload();
    await expect(page.getByRole("radio", { name: "Light" })).toBeChecked();
    await themeOption("Dark").click();
    await expect(page.getByRole("radio", { name: "Dark" })).toBeChecked();
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  });
});

test.describe("console at 320 px", () => {
  test("reflows without sideways scrolling", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 800 });
    for (const path of [
      "/console",
      "/console/runs",
      "/console/evals",
      "/console/memory",
      "/console/runbooks",
      "/console/settings",
      "/console/ask",
    ]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expectNoSidewaysScroll(page, path);
    }
    await page.getByRole("tab", { name: /Triage in chat/ }).click();
    await expectNoSidewaysScroll(page, "ask, chat");

    // On a phone the queue is a list of cards rather than a table.
    await page.goto("/console/runs?status=published");
    await page
      .getByRole("link", { name: /ZooKeeper/ })
      .first()
      .click();
    await expect(page.getByRole("heading", { name: "Severity", exact: true })).toBeVisible();
    await expectNoSidewaysScroll(page, "run view");
    for (const tab of [
      "Evidence",
      "Logs and templates",
      "Similar incidents",
      "History and forks",
    ]) {
      await page.getByRole("tab", { name: new RegExp(tab) }).click();
      await expectNoSidewaysScroll(page, `run view, ${tab}`);
    }
  });
});

test.describe("console in the light theme", () => {
  test("meets WCAG 2.2 AA", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("theme", "light"));
    await page.goto("/console/runs?status=published");
    await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
    await expectAccessible(page, "incidents, light");
    await page
      .getByRole("row", { name: /ZooKeeper/ })
      .getByRole("link")
      .click();
    await expect(page.getByRole("heading", { name: "Severity", exact: true })).toBeVisible();
    await expectAccessible(page, "run view, light");
    await page.goto("/console/evals");
    await expectAccessible(page, "evaluation, light");
  });
});
