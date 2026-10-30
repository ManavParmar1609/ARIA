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
- The API runs the [demo image](../deploy/demo/Dockerfile). It needs no API key, sends nothing to
  a model provider (every step runs on ARIA's offline provider) and starts from a demo seeded at
  build time: past incidents in memory, one approved run and two waiting for review.

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
   | `ARIA_PUBLIC_DEMO` | `1` | Tells visitors, beside the log box, that other visitors can see their runs |
   | `ENABLE_EXPERIMENTAL_COREPACK` | `1` | Installs with the pnpm version the lockfile was made with |

5. Choose **Deploy**. When it finishes, open the address Vercel gives you, such as
   `https://aria.vercel.app`.

Link previews on LinkedIn, X and Slack use the production address automatically. If you add a
custom domain later, set `ARIA_WEB_URL` to it and redeploy.

## Step 3: check it as a visitor would

1. The landing page loads and the replay plays.
2. **Open the console** shows the overview, with two incidents waiting for review.
3. In **New triage**, load a sample and choose **Start triage**. The run view follows the run
   live; when it finishes, approve it.
4. If the console says it is still connecting, the API is waking up. See the next section.

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

## What a public demo exposes

- **No sign-in.** Anyone with the address can start runs, review them and delete them. A restart
  puts everything back.
- **Visitors see each other's runs.** The console asks them to load a sample or paste only logs
  they can share.
- **Nothing leaves the server.** The demo has no model provider keys and no Slack, Teams or
  webhook targets. Keep it that way: anyone could spend a provider key on a public demo, and
  pasted text would go to the provider.
- **One shared rate limit.** Every console visitor reaches the API through Vercel's servers, so
  they share the limit of 600 requests a minute. If visitors see "rate limit exceeded", raise
  `ARIA_RATE_LIMIT_PER_MINUTE` in the Render service's **Environment** settings.

## If something goes wrong

| What you see | What to do |
|---|---|
| The Render build fails | Open the deploy's log. If it names a missing branch or file, check that the Blueprint points at the branch you merged into. |
| The console says "ARIA's API is not answering" | Check that Render shows the service as Live, and that `ARIA_API_URL` starts with `https://` and has no path after the address. Vercel applies changed variables to new deployments only, so redeploy after a change. |
| The Vercel install fails with a pnpm or lockfile error | Check that `ENABLE_EXPERIMENTAL_COREPACK` is `1`, then redeploy. |
| Visitors see "rate limit exceeded" | Raise `ARIA_RATE_LIMIT_PER_MINUTE` on Render. |
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
