import { expect, expectAccessible, expectNoSidewaysScroll, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

test.describe("console", () => {
  test("triages a sample, follows it live, and publishes it after review", async ({ page }) => {
    // The console opens on New triage, where visitors act.
    await page.goto("/console");
    await expect(page).toHaveURL(/\/console\/runs\/new$/);
    await page.getByRole("link", { name: "Incidents" }).first().click();
    await expect(page.getByText("No incidents yet.")).toBeVisible();
    await expectAccessible(page, "incidents, empty");

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
    await page.getByRole("tab", { name: "Event log" }).click();
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
    await page
      .getByRole("searchbox", { name: "Search", exact: true })
      .fill("quorum lost between peers");
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
    await page.getByRole("button", { name: /Sample: ssh brute-force attempts/i }).click();
    await page.getByRole("button", { name: "Triage in chat" }).click();
    await expect(page.getByText(/Review the incident report/)).toBeVisible();
    await expect(page.locator("li:has(svg.lucide-wrench)").first()).toBeVisible();
    await page.getByRole("button", { name: "Approve and publish" }).click();
    await expect(page.getByText(/Run published/)).toBeVisible();
  });

  test("shows evaluation, runbooks and settings", async ({ page }) => {
    for (const [path, heading] of [
      ["/console/evals", "Test results"],
      ["/console/runbooks", "Runbooks"],
      ["/console/guide/connect", "Connect ARIA to your systems"],
      // Settings comes last: the checks after this loop run on it.
      ["/console/settings", "Settings"],
    ] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await expectAccessible(page, path);
      if (path === "/console/evals") {
        // The long evaluation page opens with a link to each section.
        await page
          .getByRole("navigation", { name: "On this page" })
          .getByRole("link", { name: "GitLab.com incidents" })
          .click();
        await expect(page).toHaveURL(/#ev-gitlab$/);
        await expect(
          page.getByRole("heading", { level: 2, name: /Similar past incidents, on GitLab/ }),
        ).toBeInViewport();
      }
    }
    // Reviews from the earlier tests feed the recalibration queue.
    await expect(page.getByRole("table", { name: "Recent reviews" })).toContainText("Approved");
    await expect(page.getByText(/of 30 needed/)).toBeVisible();

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

  test("jumps anywhere from the command palette and the keyboard", async ({ page }) => {
    await page.goto("/console");
    await page.keyboard.press("Control+k");
    const search = page.getByRole("combobox", { name: /Search pages, incidents/ });
    await expect(search).toBeFocused();
    await search.fill("runbooks");
    await expect(page.getByRole("option", { name: /Runbooks/ }).first()).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expectAccessible(page, "command palette");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/console\/runbooks$/);
    await expect(page.getByRole("heading", { level: 1, name: "Runbooks" })).toBeVisible();

    await page.keyboard.press("?");
    await expect(page.getByRole("heading", { name: "Keyboard shortcuts" })).toBeVisible();
    await expectAccessible(page, "keyboard shortcuts");
    await page.keyboard.press("Escape");
    await page.keyboard.press("g");
    await page.keyboard.press("i");
    await expect(page).toHaveURL(/\/console\/runs$/);
  });

  test("guides a first visit and triages a sample in one click", async ({ page }) => {
    await page.goto("/console");
    await page.getByRole("link", { name: "Guide", exact: true }).first().click();
    await expect(page.getByRole("heading", { level: 1, name: "Guide" })).toBeVisible();
    await expect(page.getByRole("term").filter({ hasText: "Prediction set" })).toBeVisible();
    await expectAccessible(page, "guide");

    await page.getByRole("button", { name: "Triage it: SSH brute-force attempts" }).click();
    await expect(page).toHaveURL(/\/console\/runs\/run-/);
    await expect(page.getByRole("heading", { name: "Severity", exact: true })).toBeVisible();
    await page.getByRole("link", { name: "How to read this" }).click();
    await expect(page).toHaveURL(/\/console\/guide#read-a-run$/);
    await expect(page.getByRole("heading", { name: "How to read a run" })).toBeVisible();
  });

  test("replays a real incident and checks ARIA against the experts", async ({ page }) => {
    await page.goto("/console/guide");
    const card = page.locator("li", { hasText: "Silent block failures on a Hadoop cluster" });
    await expect(card.getByText("labelled failed by its experts")).toBeVisible();
    await card.getByRole("button", { name: /^Replay it: Silent block failures/ }).click();

    await expect(page).toHaveURL(/\/console\/runs\/run-/);
    await expect(page.getByText("a real incident, replayed")).toBeVisible();
    await expect(
      page.getByRole("heading", { level: 1, name: /HDFS blocks stopping partway/ }),
    ).toBeVisible({ timeout: 60_000 });
    const check = page.locator("section", {
      has: page.getByRole("heading", { name: "Check ARIA against the experts" }),
    });
    await expect(check.getByText(/^ARIA flagged \d+ blocks?\./)).toBeVisible();
    await expect(check.getByRole("table")).toContainText("Failed");
    await expect(check.getByRole("cell", { name: /^blk_/ }).first()).toBeVisible();
    await expectAccessible(page, "run view, real incident replay");
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
      "/console/guide",
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

test.describe("console on a phone", () => {
  test("meets WCAG 2.2 AA at 375 px", async ({ page }) => {
    // The phone header shows the wordmark where the sidebar was: its name must include "ARIA".
    await page.setViewportSize({ width: 375, height: 800 });
    for (const path of ["/console", "/console/runs", "/console/guide"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expectAccessible(page, `${path} at 375 px`);
    }
  });
});

test.describe("console in the dark theme", () => {
  test("meets WCAG 2.2 AA", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("theme", "dark"));
    await page.goto("/console/runs?status=published");
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await expectAccessible(page, "incidents, dark");
    await page
      .getByRole("row", { name: /ZooKeeper/ })
      .getByRole("link")
      .click();
    await expect(page.getByRole("heading", { name: "Severity", exact: true })).toBeVisible();
    await expectAccessible(page, "run view, dark");
    // The severity stamp is still landing when the page opens. Freeze it at a few frames, so a
    // stamp that dims its label fails here every time, not only when axe happens to catch it.
    for (const ms of [0, 100, 250, 400]) {
      await page.evaluate((at) => {
        for (const animation of document.getAnimations()) {
          animation.pause();
          animation.currentTime = at;
        }
      }, ms);
      await expectAccessible(page, `run view mid-stamp at ${ms} ms, dark`);
    }
    await page.goto("/console/evals");
    await expectAccessible(page, "evaluation, dark");
  });
});
