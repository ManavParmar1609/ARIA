#!/bin/bash
# SessionStart hook for Claude Code cloud sessions (web, desktop, phone or tablet).
#
# A fresh cloud container gets the same tools as the session that built ARIA:
#   1. Python dependencies, all groups, from uv.lock into .venv;
#   2. every agent skill pinned in .claude/skills.lock.tsv, into ~/.claude/skills;
#   3. the web app's dependencies, from web/pnpm-lock.yaml;
#   4. the container's preinstalled Chromium for the end-to-end tests, when the browser build
#      the pinned Playwright expects is not there (exported through CLAUDE_ENV_FILE).
# Each step runs only when a file that decides what it installs has changed since it last
# succeeded (or something it installed is missing), so later session starts are instant.
# Details go to ~/.cache/aria/session-start.log; stdout carries a one-line summary.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"
log_dir="${XDG_CACHE_HOME:-$HOME/.cache}/aria"
mkdir -p "$log_dir"
log="$log_dir/session-start.log"
: > "$log"
summary=()

fail() {
  echo "ARIA session setup failed during: $1 (see $log)" >&2
  tail -n 20 "$log" >&2
  exit 1
}

# 1. Python dependencies. The hash file lives in .venv (gitignored) and goes away with it.
hashes=.venv/.session-start.sha256
if ! sha256sum --check --status "$hashes" 2>/dev/null; then
  rm -f "$hashes"
  uv sync --all-groups --all-extras --frozen >> "$log" 2>&1 || fail "uv sync"
  sha256sum .claude/hooks/session-start.sh pyproject.toml uv.lock > "$hashes"
  summary+=("python deps installed")
else
  summary+=("python deps up to date")
fi

# 2. Agent skills. The hash file lives in the skills directory, outside the repository.
skills_dir="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
mkdir -p "$skills_dir"
skill_hashes="$skills_dir/.aria-skills.sha256"
if ! sha256sum --check --status "$skill_hashes" 2>/dev/null \
  || ! scripts/install-agent-skills.sh --check >> "$log" 2>&1; then
  rm -f "$skill_hashes"
  scripts/install-agent-skills.sh >> "$log" 2>&1 || fail "skill install"
  sha256sum .claude/hooks/session-start.sh .claude/skills.lock.tsv scripts/install-agent-skills.sh \
    > "$skill_hashes"
  summary+=("skills installed ($(grep -c '^added' "$log" || true) added)")
else
  summary+=("$(($(wc -l < .claude/skills.lock.tsv) - 1)) skills up to date")
fi

# 3. Web dependencies. Optional for Python work, so a failure is reported, not fatal.
web_hashes=web/node_modules/.session-start.sha256
if command -v pnpm > /dev/null && ! sha256sum --check --status "$web_hashes" 2>/dev/null; then
  if pnpm --dir web install --frozen-lockfile >> "$log" 2>&1; then
    sha256sum .claude/hooks/session-start.sh web/pnpm-lock.yaml > "$web_hashes"
    summary+=("web deps installed")
  else
    summary+=("web deps NOT installed (see $log)")
  fi
fi

# 4. Playwright's browser. Cloud containers ship one Chromium build; a newer pinned Playwright
# looks for its own and fails, so point the end-to-end tests at the shipped one.
shipped=/opt/pw-browsers/chromium
if [ -x "$shipped" ] && [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -z "${PLAYWRIGHT_CHROMIUM_PATH:-}" ]; then
  echo "export PLAYWRIGHT_CHROMIUM_PATH=$shipped" >> "$CLAUDE_ENV_FILE"
  summary+=("e2e browser set")
fi

echo "ARIA session setup: ${summary[*]}"
