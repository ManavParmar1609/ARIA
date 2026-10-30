# syntax=docker/dockerfile:1
#
# ARIA images. Targets:
#   api     FastAPI service (REST, SSE, MCP, A2A, AG-UI) on port 8000
#   worker  background worker that runs queued triage runs (ARIA_WORKER_MODE=external)
#   web     the Next.js landing page and console on port 3000 (it calls the API at ARIA_API_URL)
#
#   docker build --target api -t aria-api .
#
# For Azure, add the `azure` extra (Azure SQL through Microsoft's ODBC Driver 18, managed
# identity, Azure Monitor). Installing the driver accepts Microsoft's ODBC driver EULA:
#   docker build --build-arg ARIA_EXTRAS=azure --target api -t aria-api .
#
# Behind a TLS-inspecting proxy, pass its CA as a build secret; it is used for downloads only
# and never stored in an image layer:
#   docker build --secret id=ca,src=/path/to/ca.pem --target api -t aria-api .

ARG PYTHON_IMAGE=python:3.13-slim
ARG NODE_IMAGE=node:22-slim

# --- build: locked dependencies and the project, installed into /app/.venv --------------------
FROM ${PYTHON_IMAGE} AS build
ARG UV_VERSION=0.11.32
ARG ARIA_EXTRAS=""
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN --mount=type=secret,id=ca,required=false \
    --mount=type=cache,target=/root/.cache/pip \
    if [ -s /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install "uv==${UV_VERSION}"
# Dependencies first, so code changes reuse this layer.
RUN --mount=type=secret,id=ca,required=false \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    if [ -s /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca UV_SYSTEM_CERTS=1; fi; \
    uv sync --locked --no-install-project --no-dev ${ARIA_EXTRAS:+--extra "$ARIA_EXTRAS"}
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=secret,id=ca,required=false \
    --mount=type=cache,target=/root/.cache/uv \
    if [ -s /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca UV_SYSTEM_CERTS=1; fi; \
    uv sync --locked --no-dev --no-editable ${ARIA_EXTRAS:+--extra "$ARIA_EXTRAS"}

# --- runtime: the virtual environment, configuration, runbooks and the trained model ----------
FROM ${PYTHON_IMAGE} AS runtime
ARG ARIA_EXTRAS=""
# Azure SQL needs Microsoft's ODBC driver, from Microsoft's package repository for this Debian.
# (The CA is readable by apt's unprivileged fetcher; like every secret mount, it is not kept.)
RUN --mount=type=secret,id=ca,required=false,mode=0444 \
    if [ "$ARIA_EXTRAS" = "azure" ]; then \
      set -eu; \
      ca=/etc/ssl/certs/ca-certificates.crt; \
      if [ -s /run/secrets/ca ]; then ca=/run/secrets/ca; fi; \
      . /etc/os-release; \
      SSL_CERT_FILE="$ca" python -c "import urllib.request as u; u.urlretrieve('https://packages.microsoft.com/config/debian/${VERSION_ID}/packages-microsoft-prod.deb', '/tmp/ms.deb')"; \
      dpkg -i /tmp/ms.deb; \
      rm /tmp/ms.deb; \
      sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
      apt-get -o Acquire::https::CaInfo="$ca" update; \
      ACCEPT_EULA=Y apt-get -o Acquire::https::CaInfo="$ca" install -y --no-install-recommends \
        msodbcsql18 unixodbc; \
      rm -rf /var/lib/apt/lists/*; \
    fi
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    ARIA_ENV=prod \
    ARIA_LOG_FORMAT=json \
    ARIA_DATABASE_URL=sqlite:////var/lib/aria/aria.db \
    ARIA_DATA_DIR=/var/lib/aria/data \
    ARIA_MODELS_DIR=/var/lib/aria/models
RUN groupadd --system --gid 10001 aria \
    && useradd --system --uid 10001 --gid aria --home-dir /app --shell /usr/sbin/nologin aria \
    && mkdir -p /var/lib/aria/data /var/lib/aria/models \
    && chown -R aria:aria /var/lib/aria
WORKDIR /app
COPY --from=build --chown=aria:aria /app/.venv /app/.venv
COPY --chown=aria:aria config ./config
COPY --chown=aria:aria runbooks ./runbooks
# The trained models: log severity, and the ticket priority and SLA models (UCI log).
COPY --chown=aria:aria models/severity_log.json models/severity_log.report.json \
     models/severity_ticket.json ./models/
# The evaluation results released with this build, served at /api/v1/eval.
COPY --chown=aria:aria docs/eval-results.json ./docs/eval-results.json
# Small public Loghub samples: `aria seed` falls back to them when the full set is not downloaded.
COPY --chown=aria:aria tests/fixtures/loghub ./tests/fixtures/loghub
COPY --chown=aria:aria tests/fixtures/real ./tests/fixtures/real
USER aria
VOLUME ["/var/lib/aria"]

FROM runtime AS worker
HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --retries=4 \
    CMD ["aria", "worker-health", "--max-age", "60"]
CMD ["aria", "worker"]

FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=6 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status != 200)"]
CMD ["aria", "serve", "--host", "0.0.0.0", "--port", "8000"]

# --- web-build: the Next.js app, compiled to a standalone server ---------------------------------
FROM ${NODE_IMAGE} AS web-build
ARG PNPM_VERSION=10.28.0
# The site's public URL. Pages are prerendered here, so their absolute links (the social preview
# image, for one) take it from the build, not from the running container.
ARG ARIA_WEB_URL=""
ENV NEXT_TELEMETRY_DISABLED=1 \
    CI=1
WORKDIR /web
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    npm install --global --no-fund --no-audit "pnpm@${PNPM_VERSION}"
# Dependencies first, so code changes reuse this layer. The lockfile is frozen, and pnpm runs no
# dependency install scripts (pnpm-workspace.yaml).
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN --mount=type=secret,id=ca,required=false \
    --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    if [ -s /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    pnpm install --frozen-lockfile --store-dir /pnpm/store
COPY web/ ./
RUN ARIA_WEB_URL="${ARIA_WEB_URL}" pnpm build

# --- web: the standalone server and its static files, as an unprivileged user --------------------
FROM ${NODE_IMAGE} AS web
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    ARIA_API_URL=http://api:8000
RUN groupadd --system --gid 10001 aria \
    && useradd --system --uid 10001 --gid aria --home-dir /app --shell /usr/sbin/nologin aria
WORKDIR /app
COPY --from=web-build --chown=aria:aria /web/.next/standalone ./
COPY --from=web-build --chown=aria:aria /web/.next/static ./.next/static
USER aria
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
    CMD ["node", "-e", "fetch(`http://127.0.0.1:${process.env.PORT}/api/healthz`).then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
CMD ["node", "server.js"]
