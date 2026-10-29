#!/usr/bin/env bash
# Reinstall the agent skills used to build ARIA, pinned to the reviewed commits in
# .claude/skills.lock.tsv. Each repository is cloned into a temporary directory, checked out at
# the pinned commit, and only the listed skill folders are copied into ~/.claude/skills.
set -euo pipefail

lock="$(dirname "$0")/../.claude/skills.lock.tsv"
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$dest"

tail -n +2 "$lock" | while IFS=$'\t' read -r name repo commit path; do
  if [[ -e "$dest/$name" ]]; then
    echo "skip   $name (already installed)"
    continue
  fi
  checkout="$work/${repo//\//_}"
  if [[ ! -d "$checkout/.git" ]]; then
    git init -q "$checkout"
    git -C "$checkout" remote add origin "https://github.com/$repo"
  fi
  git -C "$checkout" fetch -q --depth 1 origin "$commit"
  git -C "$checkout" checkout -q FETCH_HEAD
  cp -r "$checkout/$path" "$dest/$name"
  echo "added  $name  ($repo@${commit:0:7})"
done
