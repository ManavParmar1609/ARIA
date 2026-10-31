# Deploy a free public demo

This guide puts ARIA online so anyone can read the landing page and try the console. It costs
nothing:

- the website (landing page and console) runs on Vercel's free Hobby plan;
- the API runs on Render's free web service plan.

Free plans change, so check each host's current terms before you rely on them. This guide was
written in October 2026.

For a production deployment with API keys, a managed database and monitoring, see
[Deploying to Azure](../README.md#deploying-to-azure) instead.

## How it fits together

```text
visitor ──▶ Vercel: landing page, console, /api/* proxy ──▶ Render: ARIA API, seeded demo
```

- The landing page needs no API. It shows a recorded run and the published results, so it stays
  up and fast even while the API sleeps.
- The console reaches the API through Vercel's server. The browser never talks to Render
  directly.
- The API runs the [demo image](../deploy/demo/Dockerfile). It needs no API key and starts from a
  demo seeded at build time: past incidents in memory, one approved run and two waiting for
  review, and each sample's sizes already rated, so the first visitor after a wake-up does not
  wait for them. Every step runs on ARIA's offline provider, unless a visitor brings their own model key
  or you set one (see [Language models on the demo](#language-models-on-the-demo)).

## Before you start

1. Merge the pull request into `main`, so both hosts deploy the finished code. To deploy another
   branch, choose it in each host's settings.
2. Have a GitHub account with access to the repository. You will sign in to Vercel and Render with
   it.
3. Allow about 20 minutes, most of it waiting for the first build.

## Step 1: put the API on Render

1. Open [dashboard.render.com](https://dashboard.render.com) and sign in with GitHub.
2. Choose **New**, then **Blueprint**. Connect GitHub if asked and pick the ARIA repository.
   Render reads [render.yaml](../render.yaml) and proposes one free web service, `aria-api`.
3. Choose **Apply**. If the plan shown is not **Free**, pick Free first.
4. Wait for the first build. It installs ARIA and seeds the demo into the image, which takes a
   while on Render's free builders.
5. When the service shows **Live**, copy its address, for example
   `https://aria-api.onrender.com`. Render adds a suffix when the name is taken.
6. Check it:
   - `<address>/healthz` answers `{"status":"ok",...}`;
   - `<address>/docs` shows the interactive API reference.

## Step 2: put the website on Vercel

1. Open [vercel.com/new](https://vercel.com/new), sign in with GitHub and choose the Hobby plan.
2. Import the ARIA repository.
3. Set **Root Directory** to `web`. Vercel detects Next.js; leave the build and install commands
   as they are.
   - [web/vercel.json](../web/vercel.json) installs and builds with pnpm 10.28.0, the version the
     lockfile was made with. Without it, Vercel can fall back to pnpm 6, which fails on current
     Node.js with `ERR_INVALID_THIS`.
   - Beside the `web` folder, Vercel may say "No services detected". That is expected: the folder
     holds one app, so there is nothing to combine into services. Keep the framework on Next.js.
   - If you leave the root directory at the repository root instead, the root
     [vercel.json](../vercel.json) points Vercel at `web/` as its one service. Without it, Vercel
     would find the Python API and `render.yaml` there and stop.
   - Fixing a project you already imported: change its root directory in **Settings**, then
     deploy the newest commit on `main`. **Redeploy** on an older deployment rebuilds that
     deployment's commit.
4. Add these environment variables:

   | Name | Value | Why |
   |---|---|---|
   | `ARIA_API_URL` | Your Render address, such as `https://aria-api.onrender.com` | Where the console's server finds the API |
   | `ARIA_PUBLIC_DEMO` | `1` | Tells visitors, beside the log box, that the demo runs on a shared server, so they paste only logs they could share |

5. Choose **Deploy**. When it finishes, open the address Vercel gives you, such as
   `https://aria.vercel.app`.

Link previews on LinkedIn, X and Slack use the production address automatically. If you add a
custom domain later, set `ARIA_WEB_URL` to it and redeploy.

## Step 3: check it as a visitor would

1. The home page loads. In its example incident, pointing at a citation lights up the log lines
   behind it.
2. **Open the console** opens **New triage**. **Incidents** lists the examples: two waiting for
   review and one approved.
3. In **New triage**, choose **Run it** on a sample. The incident page follows the run live; when
   it waits for you, approve it.
4. If the console says ARIA's server is waking up, wait a minute. See the next section.
5. Before you share the link, stress the API from your own machine the way many visitors would
   use it at once:

   ```bash
   uv run python -I scripts/stress_demo.py --base https://<your-api>.onrender.com --visitors 12
   ```

   It should end with "no problems": no server errors, no visitor seeing another's incidents, and
   a clear refusal for every bad request. It stops at once if the API has a model key of its own,
   because every simulated visitor would spend that key's allowance.

## What to expect from the free plans

- **The API sleeps after 15 minutes without visitors.** The next visit wakes it within about a
  minute, and the console says it is still connecting meanwhile. Open the console a minute before
  you show it to someone.
- **The demo resets** whenever the API restarts or wakes. It always starts again from the seeded
  runs, so nothing visitors do is kept.
- **Runs take a few seconds.** The free plan gives the API a tenth of a CPU, so the pipeline that
  takes under a second on a laptop is slower there.
- **Monthly limits.** Render's free plan includes 750 instance hours a month, enough for one
  service all month. Vercel's Hobby plan is for personal, non-commercial projects.
- **Request limits.** A Vercel function runs for up to 300 seconds, so a live run's event stream
  reconnects after that, and the console picks up where it left off. Vercel also caps request
  bodies at 4.5 MB, which is less than the console's own limit, so the largest pastes need the
  API or the command line.
- **Updates.** Both hosts redeploy on every push to `main`: Render rebuilds the image and Vercel
  rebuilds the site. If you push often, turn off Auto-Deploy in the Render service's settings and
  deploy by hand.

## Language models on the demo

Out of the box the demo uses no language model: rules, the calibrated model and the grounded
report template do the work, and nothing leaves the server. Two ways bring a model in.

### Visitors bring their own key

The demo image sets `ARIA_VISITOR_KEYS=true`, so the console's **Settings** page shows a **Your
model key** section. A visitor picks Claude, Gemini, OpenAI or NVIDIA NIM, pastes a key and
chooses **Check and save key**.

- ARIA checks the key with the provider first and keeps only a key the provider accepts.
- The visitor's browser keeps the key in a cookie that page scripts cannot read, for up to a
  working day, and sends it only with requests that can call a model.
- The API uses it for that visitor's runs and questions alone, holds it in memory while they run,
  and never stores, logs or shows it.
- Their logs, after ARIA's redaction, go to the provider they chose, and the cost falls on their
  key, capped per run by ARIA's budget.

Nothing costs you anything. To turn it off, set `ARIA_VISITOR_KEYS=false` in the Render service's
**Environment** settings.

### Each visitor sees only their own incidents

The demo image also sets `ARIA_VISITOR_SCOPE=true`, so visitors who share the link never see one
another's work.

- The console gives each browser a private session id, in a cookie page scripts cannot read, and
  sends it with every request. The API files each new incident under a hash of that id.
- A visitor's **Incidents** page lists the incidents they started, plus the three examples the
  image triaged when it was built. The examples are marked **Example**.
- Nobody can review, send or delete an example, so it is the same for the next visitor. **Make my
  own copy** on an example gives the visitor a private copy to review.
- A visitor's incidents never join the incident library, the templates other runs are compared
  with, or the reviews that recalibrate the severity model.
- Anyone calling the API directly without a session id shares one anonymous space, and a caller
  with an API key still sees every incident.

### You set your own key

Add your key as an environment variable on Render (for example `GEMINI_API_KEY`), then choose
**Save and deploy**; **Save only** keeps the variable but the running service does not see it
until its next deploy. Check it in the console under **Settings**, **Model providers**: the
provider's row should say **Ready**.

Every visitor without a key of their own then uses yours, within a daily allowance the demo image
sets: 5 model-written runs and answers per visitor, and 100 for everyone together, per UTC day.
Past either, that visitor's work runs offline, which still works end to end, and the console says
so: **Settings** and **New triage** show "The site's key (shared, limited)" with what is left
today, then "Offline". A visitor's own key always comes first and never counts against yours.
Change the allowance with `ARIA_SHARED_PER_VISITOR` and `ARIA_SHARED_PER_DAY` (0 means no limit).

Before you add your key, weigh three things:

- **Cost.** A free-tier key (Google AI Studio without billing, for example) costs nothing: when its
  daily quota runs out, runs fall back to the offline path until it resets. With billing, the cost
  is at most the daily allowance times one run's budget, since ARIA caps each run's tokens, calls
  and time. The counts live in the service's memory, so a restart (the free plan sleeps after 15
  minutes without visitors) starts the day's count afresh.
- **Quota.** Visitors share your key's provider quota; the per-visitor allowance keeps one busy
  visitor from using it all. A visitor is a browser session, so clearing cookies starts a new
  share: the daily total is the real cap.
- **Privacy.** Visitors' pasted logs, after redaction, go to your provider account. On Gemini's
  free tier, Google may use prompts to improve its products.

## What a public demo exposes

- **No sign-in.** Anyone with the address can start triages, review them and delete them. A
  restart puts everything back.
- **Each visitor sees only their own incidents.** A visitor is a browser session: it sees the
  incidents it started, plus the shared examples, which nobody can change or delete. The console
  still asks visitors to paste only logs they could share, because the server is shared.
- **Nothing goes to a model unless a key is there.** The demo has no model provider keys of its
  own and no Slack, Teams or webhook targets. A visitor who saves their own key sends their own
  triages to their chosen provider. A key you set yourself serves every other visitor within the
  daily allowance, alerts and agent tasks included, and past it their work runs offline (see
  [Language models on the demo](#language-models-on-the-demo)).
- **A rate limit for each visitor, and one for the site.** Each visitor may make 120 requests a
  minute, and since every console visitor reaches the API through Vercel's servers, all of them
  together may make 1,800. When either runs out, the console says ARIA is busy and carries on by
  itself a few seconds later. To allow more, raise `ARIA_RATE_LIMIT_PER_MINUTE` (each visitor) or
  `ARIA_RATE_LIMIT_SITE_PER_MINUTE` (everyone) in the Render service's **Environment** settings.
- **Room for everyone in the queue.** The free plan runs one triage at a time, so each visitor may
  have 3 waiting or running; the console asks for a fourth to wait until one is ready
  (`ARIA_MAX_ACTIVE_RUNS_PER_VISITOR`).
- **Pastes up to 1 MB.** A run's memory grows with its lines, and the free plan has 512 MB, so the
  demo takes pastes of up to 1 MB, about 5,000 log lines; the console says so before sending a
  larger one. On a server with more memory, raise `ARIA_MAX_BODY_BYTES` (in bytes).

## If something goes wrong

| What you see | What to do |
|---|---|
| The Render build fails | Open the deploy's log. If it names a missing branch or file, check that the Blueprint points at the branch you merged into. |
| The console says "ARIA's API is not answering" | Check that Render shows the service as Live, and that `ARIA_API_URL` starts with `https://` and has no path after the address. Vercel applies changed variables to new deployments only, so redeploy after a change. |
| The Vercel install fails with `ERR_INVALID_THIS` or a lockfile error | Vercel used its own pnpm instead of `web/vercel.json`'s. Check that the project's root directory is `web` and that no install command override is set, then deploy the newest commit on `main`. |
| The console often says ARIA is busy | Raise `ARIA_RATE_LIMIT_SITE_PER_MINUTE` on Render, or `ARIA_RATE_LIMIT_PER_MINUTE` if one visitor sees it alone. |
| Render restarts the API saying it ran out of memory | Lower `ARIA_MAX_BODY_BYTES`, or move to a plan with more memory. |
| Link previews show no image | Set `ARIA_WEB_URL` to your site's address and redeploy. |

## Other places to run the API

The demo image runs on any container host. It listens on `$PORT` (8000 if unset) and names its
public address in links when `ARIA_PUBLIC_BASE_URL` is set.

```bash
docker build -f deploy/demo/Dockerfile -t aria-demo .
```

```bash
docker run --rm -p 8000:8000 aria-demo
```

- **Google Cloud Run** has a free monthly allowance but needs a billing account with a card.
  Push the image to Artifact Registry and deploy it with at most one instance, so every visitor
  sees the same demo. Set `ARIA_PUBLIC_BASE_URL` to the service's address.
- **Oracle Cloud's Always Free** virtual machines stay on all the time, with no sleep, but sign-up
  needs a card to verify you. Run the image there behind a reverse proxy, such as Caddy, for
  HTTPS.
- **Hugging Face Spaces** no longer fits. Since July 2026, Docker Spaces need a paid plan; free
  accounts can host only static Spaces and ZeroGPU Gradio Spaces.
- **Azure**, through this repository's `azd` setup, is the production deployment. Its container
  registry and monitoring are billed, so it is not free.
