# ARIA's API as a public demo: open, offline unless a visitor brings a model key, and seeded.
#
# Built from the repository root, so the image matches the commit being deployed:
#   docker build -f deploy/demo/Dockerfile -t aria-demo .
#   docker run --rm -p 8000:8000 aria-demo
# Render builds it from render.yaml. docs/deploy-free.md has the steps for Render and others.
#
# A free host keeps nothing on disk across restarts, and neither does this image: the demo is
# seeded at build time, so every start (and every wake from sleep) begins from the same state.

ARG PYTHON_IMAGE=python:3.13-slim

# --- build: locked dependencies and ARIA, installed into /app/.venv ---------------------------
FROM ${PYTHON_IMAGE} AS build
ARG UV_VERSION=0.11.32
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
# Behind a TLS-inspecting proxy, pass its CA as the secret `ca` (see the root Dockerfile). Hosted
# builders have none, so these steps download as usual.
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir "uv==${UV_VERSION}"
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca UV_SYSTEM_CERTS=1; fi; \
    uv sync --locked --no-dev --no-editable --no-cache

# --- demo: the API and its seeded demo, run as an unprivileged user ----------------------------
FROM ${PYTHON_IMAGE}
# User 1000, which some hosts insist on.
RUN useradd --create-home --uid 1000 aria
# A public demo: no API key (anyone may try it) and no Slack, Teams or webhook targets. Every step
# runs on the offline provider unless a visitor brings a key or the service is given one (below).
# Visitors may paste their own Claude, Gemini, OpenAI or NVIDIA key in the console's Settings: it
# answers only their own runs and questions, sending them to that provider, and is held in memory
# while they run, never stored. Each visitor sees only the incidents they started, plus the seeded
# examples, which nobody can change or delete. The rate limit is shared, since every console
# visitor arrives through one proxy, and a request may carry at most 8 MB, as through the console.
# Runs go one at a time, so a few large ones arriving together stay inside a free plan's 512 MB.
# With a model key set on the service (GEMINI_API_KEY, say), a visitor without a key of their own
# gets 5 model-written runs and answers a day, and everyone together 100; past that, offline.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    ARIA_ENV=dev \
    ARIA_LOG_FORMAT=json \
    ARIA_WORKER_MODE=inprocess \
    ARIA_VISITOR_KEYS=true \
    ARIA_VISITOR_SCOPE=true \
    ARIA_SHARED_PER_VISITOR=5 \
    ARIA_SHARED_PER_DAY=100 \
    ARIA_WORKER_CONCURRENCY=1 \
    ARIA_RATE_LIMIT_PER_MINUTE=600 \
    ARIA_MAX_BODY_BYTES=8388608 \
    ARIA_DATABASE_URL=sqlite:////home/aria/demo/aria.db \
    ARIA_DATA_DIR=/home/aria/demo/data \
    ARIA_MODELS_DIR=/home/aria/demo/models
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY config ./config
COPY runbooks ./runbooks
COPY models/severity_log.json models/severity_log.report.json \
     models/severity_ticket.json ./models/
COPY docs/eval-results.json ./docs/eval-results.json
COPY tests/fixtures/loghub ./tests/fixtures/loghub
COPY tests/fixtures/real ./tests/fixtures/real
USER aria
# Incident memory from the bundled Loghub samples (as `docker compose up` seeds it), one approved
# run and two waiting for review.
RUN mkdir -p /home/aria/demo/data /home/aria/demo/models \
    && aria db upgrade \
    && aria seed --workers 2 \
    && aria triage --scenario zookeeper.quorum_connection_loss --approve \
    && aria triage --scenario bgl.kernel_panic \
    && aria triage --scenario openssh.bruteforce
EXPOSE 8000
# Hosts pass the port in PORT. Links the API hands out name its public address: ARIA_PUBLIC_BASE_URL
# when set, else the one Render gives the service.
CMD ["sh", "-c", "base=\"${ARIA_PUBLIC_BASE_URL:-${RENDER_EXTERNAL_URL:-}}\"; if [ -n \"$base\" ]; then export ARIA_PUBLIC_BASE_URL=\"$base\"; fi; exec aria serve --host 0.0.0.0 --port \"${PORT:-8000}\""]
