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
    // Samples are grouped by where their logs come from; the choice stays in the address.
    await page
      .getByRole("navigation", { name: "Where the logs come from" })
      .getByRole("link", { name: /^Big-data clusters/ })
      .click();
    await expect(page).toHaveURL(/\/console\/runs\/new\?source=bigdata$/);
    await expectAccessible(page, "new triage");
    await page
      .getByRole("button", { name: "Run it: Coordination servers lose touch with each other" })
      .click();

    await expect(page).toHaveURL(/\/console\/runs\/run-/);
    await expect(page.getByRole("heading", { name: "Waiting for your review" })).toBeVisible();
    // The answer first: the level and its word, then the short list in words.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(
      page.getByText(
        /^(Only SEV\d is likely\.|Probably SEV\d\. ARIA isn't sure enough to decide alone, so please confirm\.|Could be SEV\d.*ARIA plans for SEV\d\.( Please confirm\.)?)$/,
      ),
    ).toBeVisible();
    // Four panels, one question each.
    for (const name of ["What happened", "How serious", "Seen before", "The report"]) {
      await expect(page.getByRole("heading", { level: 2, name, exact: true })).toBeVisible();
    }
    // ARIA's part is over, so the progress folds into one line that opens onto the eight steps.
    await page.getByText(/^ARIA finished in /).click();
    await expect(
      page.getByRole("list", { name: "Run progress" }).getByRole("listitem"),
    ).toHaveCount(8);
    await expect(page.getByText(/Validated: \d+ claims, 100% cited/)).toBeVisible();

    // hover-to-evidence: a citation fills the evidence panel
    const citation = page.getByRole("button", { name: /^Evidence E\d+: Log template/ }).first();
    await citation.hover();
    await expect(page.locator("#evidence-panel")).toContainText("Log template");
    await expectAccessible(page, "run view, awaiting review");

    // No channel is connected on the test server: the drafted messages are previews to read,
    // with nothing to tick, and approving publishes the report alone.
    await page.getByText(/^\d+ message previews?/).click();
    await expect(page.getByRole("checkbox")).toHaveCount(0);
    await expect(
      page.getByText(/^ARIA’s own check: all \d+ claims cite their evidence/),
    ).toBeVisible();
    await page.getByRole("button", { name: "Approve and publish" }).click();
    // The panel becomes a receipt in place, and takes focus.
    const receipt = page.getByRole("heading", { name: "Published", exact: true });
    await expect(receipt).toBeFocused();
    await expect(
      page.getByText(
        /^Drafted by ARIA, approved by you at \d\d:\d\d\. \d+ previews? kept \(no channel connected\)\.$/,
      ),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Postmortem draft (Markdown)" })).toBeVisible();
    // A sample's page then offers ways to keep exploring.
    const next = page.locator("section", {
      has: page.getByRole("heading", { name: "What next?" }),
    });
    await expect(next.getByRole("link", { name: "Ask about this incident" })).toHaveAttribute(
      "href",
      /\/console\/ask\?run=run-/,
    );
    // Once finished, the progress folds into one line.
    await expect(page.getByText(/^ARIA finished in /)).toBeVisible();
    await page.getByRole("tab", { name: "What ARIA did" }).click();
    await page.getByText(/^Every event \(\d+\)$/).click();
    const events = page.locator("details", { has: page.getByText(/^Every event \(\d+\)$/) });
    await expect(events.getByText(/^Approved by /)).toBeVisible();
    await expect(page.getByText(/Run finished: published/)).toBeVisible();

    // time travel: view the run as it was before the review, then come back
    await page.getByRole("tab", { name: "History and forks" }).click();
    await page
      .locator("li", { hasText: "Paused at “Your review”" })
      .getByRole("button", { name: "View" })
      .click();
    await expect(page.getByText(/as it was earlier/)).toBeVisible();
    await expect(
      page.getByText("Draft: nothing has been sent. A reviewer must approve it first."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Back to now" }).click();
    await expect(page.getByText(/as it was earlier/)).toBeHidden();
  });

  test("runs a sample at a bigger size and shows both ratings", async ({ page }) => {
    await page.goto("/console/runs/new?source=security");
    await expect(
      page
        .getByRole("navigation", { name: "Where the logs come from" })
        .getByRole("link", { name: /^Security and sign-ins/ }),
    ).toHaveAttribute("aria-current", "true");
    const browse = page.locator("section", {
      has: page.getByRole("heading", { name: "Where do the logs come from?" }),
    });
    const card = browse
      .getByRole("listitem")
      .filter({ has: page.getByRole("heading", { name: "Someone keeps guessing passwords" }) });
    await card.getByText(/^Show \d+ real lines$/).click();
    await expect(card.locator("pre")).toBeVisible();
    // Only sizes that change the rating are offered (`aria seed` rated them); the smallest first.
    const sizes = card.getByRole("radio");
    await expect(sizes.first()).toBeChecked();
    const smallest = (await sizes.first().getAttribute("value")) ?? "";
    const largest = (await sizes.last().getAttribute("value")) ?? "";
    await card.getByText(`${largest} servers`, { exact: true }).click();
    await expect(sizes.last()).toBeChecked();
    await card.getByText(`${smallest} servers`, { exact: true }).click();
    await card.getByRole("button", { name: "Run it: Someone keeps guessing passwords" }).click();

    await expect(page).toHaveURL(/\/console\/runs\/run-/);
    const first = new URL(page.url()).pathname;
    // Discarded, not approved: an approved incident's templates join the server's history and
    // would change how the next run rates.
    const discard = async () => {
      await page.getByRole("button", { name: "Discard draft" }).click();
      await page.getByRole("button", { name: "Discard the draft" }).click();
      await expect(page.getByRole("heading", { name: "Draft discarded" })).toBeVisible();
    };
    // Closing a review dialog puts focus back on the button that opened it, and the edit
    // dialog opens on itself rather than on a selected title.
    const edit = page.getByRole("button", { name: "Edit before sending" });
    await edit.click();
    await expect(
      page.getByRole("dialog", { name: "Edit the report before sending" }),
    ).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(edit).toBeFocused();
    const discarding = page.getByRole("button", { name: "Discard draft" });
    await discarding.click();
    await page.getByRole("button", { name: "Keep reviewing" }).click();
    await expect(discarding).toBeFocused();
    await discard();
    const bigger = page.getByRole("button", { name: /^Run it on \d+ servers$/ });
    const next = (await bigger.textContent())?.match(/\d+/)?.[0] ?? "";
    await bigger.click();

    await expect(page).toHaveURL(/\/console\/runs\/run-[^?]+\?compare=run-/);
    await discard();
    const compared = page.getByText("The same sample at two sizes").locator("..");
    const before = compared.getByRole("link", {
      name: new RegExp(`The first run, on ${smallest} servers`),
    });
    await expect(before).toHaveAttribute("href", first);
    const after = compared.getByText(`This run, on ${next} servers`);
    await expect(after).toBeVisible();
    // The bigger size changes the rating: that is why it is offered.
    const level = /SEV[1-4]/;
    expect((await after.textContent())?.match(level)?.[0]).not.toBe(
      (await before.textContent())?.match(level)?.[0],
    );
    await expectAccessible(page, "run view, two sizes compared");
  });

  test("lists each sample once, shows the rest on request and keeps Back working", async ({
    page,
  }) => {
    await page.goto("/console/runs/new");
    // The featured cards are not repeated in the list below them.
    await expect(
      page.getByRole("button", { name: "Run it: Someone keeps guessing passwords" }),
    ).toHaveCount(1);
    const browse = page.locator("section", {
      has: page.getByRole("heading", { name: "Where do the logs come from?" }),
    });
    const more = browse.getByRole("button", { name: /^Show \d+ more$/ });
    const hidden = Number((await more.textContent())?.match(/\d+/)?.[0]);
    const shown = await browse.getByRole("listitem").count();
    await more.click();
    await expect(browse.getByRole("listitem")).toHaveCount(shown + hidden);
    await expect(more).toHaveCount(0);

    await page
      .getByRole("navigation", { name: "Where the logs come from" })
      .getByRole("link", { name: /^False alarms/ })
      .click();
    await expect(page).toHaveURL(/\/console\/runs\/new\?source=noise$/);
    await expect(browse.getByRole("button", { name: /^Run it: / })).toHaveCount(3);
    await page.goBack();
    await expect(page).toHaveURL(/\/console\/runs\/new$/);
  });

  test("triages pasted logs from the Your own logs tab", async ({ page }) => {
    await page.goto("/console/runs/new");
    await page.getByRole("tab", { name: "Your own logs" }).click();
    await expect(page).toHaveURL(/\/console\/runs\/new\?tab=own$/);
    await page.getByRole("button", { name: "Start a triage" }).click();
    await expect(page.getByText("Paste at least one log line")).toBeVisible();
    await page
      .getByLabel("Log lines")
      .fill(
        [
          "Dec 10 06:55:46 LabSZ sshd[24200]: Failed password for root from 203.0.113.9 port 22 ssh2",
          "Dec 10 06:55:48 LabSZ sshd[24202]: Failed password for root from 203.0.113.9 port 22 ssh2",
        ].join("\n"),
      );
    await expect(page.getByText("2 lines", { exact: true })).toBeVisible();
    await expectAccessible(page, "new triage, your own logs");
    await page.getByRole("button", { name: "Start a triage" }).click();
    await expect(page).toHaveURL(/\/console\/runs\/run-/);
    await expect(page.getByRole("heading", { name: "Waiting for your review" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "What next?" })).toHaveCount(0);
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

  test("answers a question with numbered sources and keeps suggestions in view", async ({
    page,
  }) => {
    await page.goto("/console/ask");
    await page.getByLabel("Your question").fill("How was ZooKeeper quorum loss fixed before?");
    await page.getByRole("button", { name: "Ask ARIA" }).click();
    const answer = page.getByRole("list", { name: "Answers" }).locator(":scope > li").first();
    const first = answer.getByRole("button", { name: /^Source 1: Past incident, / }).first();
    await expect(first).toBeVisible();
    await expect(answer.getByRole("heading", { name: "Sources" })).toBeVisible();
    // A screen reader hears that the answer came, and how much it holds.
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: /^ARIA answered: \d+ points?, from \d+ sources?\.$/ }),
    ).toHaveCount(1);
    // A citation opens its source in the list beneath the answer.
    await first.click();
    await expect(answer.locator("details[open]").first()).toContainText("Resolution:");
    await expect(
      page.getByRole("button", { name: /^Have we seen ZooKeeper lose quorum before/ }),
    ).toBeVisible();
    await expectAccessible(page, "ask");

    await page.getByLabel("Your question").fill("What is the weather in Lisbon today?");
    await page.getByRole("button", { name: "Ask ARIA" }).click();
    const nothing = "Nothing in ARIA's records answers this.";
    await expect(page.getByRole("list", { name: "Answers" }).getByText(nothing)).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: nothing })).toHaveCount(1);
  });

  test("triages in chat over AG-UI and answers the review interrupt", async ({ page }) => {
    await page.goto("/console/guide/connect");
    await page.getByRole("button", { name: /Sample: Someone keeps guessing passwords/ }).click();
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
        // Four plain questions first, then one closed card per test.
        for (const question of [
          "Does it say when it isn't sure?",
          "Does it catch serious problems without crying wolf?",
          "Does it find the right past incident?",
          "Where does it fall short, and why?",
        ]) {
          await expect(page.getByRole("heading", { level: 2, name: question })).toBeVisible();
        }
        const card = page.getByRole("region", { name: "GitLab.com's incidents" });
        await expect(card.getByRole("table").first()).toBeHidden();
        await card.getByText("Show details").click();
        await expect(card.getByRole("table").first()).toBeVisible();
      }
    }
    // Settings leads with the model. The deployment's own settings are folded away until asked for;
    // there, reviews from the earlier tests feed the recalibration queue.
    await expect(page.getByRole("heading", { level: 2 }).first()).toHaveText("Language model");
    await expect(page.getByRole("table", { name: "Recent reviews" })).toBeHidden();
    await page.getByText("Deployment details").click();
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

    await page
      .getByRole("button", { name: "Triage a sample: Someone keeps guessing passwords" })
      .click();
    await expect(page).toHaveURL(/\/console\/runs\/run-/);
    await expect(page.getByRole("heading", { name: "How serious", exact: true })).toBeVisible();
    const incident = page.url();
    await page.getByRole("link", { name: "How to read this" }).click();
    await expect(page).toHaveURL(/\/console\/guide\?from=[^#]+#read-a-run$/);
    await expect(page.getByRole("heading", { name: "Read a severity rating" })).toBeVisible();
    // The guide offers the way back to the incident it was opened from.
    await page.getByRole("link", { name: "Back to the incident" }).click();
    await expect(page).toHaveURL(incident);
  });

  test("replays a real incident and checks ARIA against the experts", async ({ page }) => {
    // Real incidents live on New triage, beside the samples from the same kind of system.
    await page.goto("/console/runs/new?source=bigdata");
    const card = page.locator("li", { hasText: "Silent block failures on a Hadoop cluster" });
    await expect(card.getByText(/Experts marked each block healthy or failed/)).toBeVisible();
    await card.getByRole("button", { name: /^Replay it: Silent block failures/ }).click();

    await expect(page).toHaveURL(/\/console\/runs\/run-/);
    await expect(page.getByText("a real incident, replayed")).toBeVisible();
    // The incident keeps the name its card gave it.
    await expect(
      page.getByRole("heading", { level: 1, name: /Silent block failures on a Hadoop cluster/ }),
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
      "/console/guide/connect",
      "/console/ask",
    ]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expectNoSidewaysScroll(page, path);
    }

    // On a phone the queue is a list of cards rather than a table.
    await page.goto("/console/runs?status=published");
    await page
      .getByRole("link", { name: /ZooKeeper/ })
      .first()
      .click();
    await expect(page.getByRole("heading", { name: "How serious", exact: true })).toBeVisible();
    await expectNoSidewaysScroll(page, "run view");
    for (const tab of ["What ARIA did", "Evidence", "Logs", "History and forks"]) {
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
    await expect(page.getByRole("heading", { name: "How serious", exact: true })).toBeVisible();
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
