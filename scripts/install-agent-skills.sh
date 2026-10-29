#!/usr/bin/env bash
# Reinstall the agent skills used to build ARIA, pinned to the reviewed commits in
# .claude/skills.lock.tsv. Each repository is fetched at the pinned commit into a temporary
# directory and only the listed skill folder is copied into ~/.claude/skills. A path of the form
# "a+b+c" copies just those items from the repository root (used when a skill repository also
# contains CI scripts that are not part of the skill).
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
  checkout="$work/${repo//\//_}-${commit:0:12}"
  if [[ ! -d "$checkout/.git" ]]; then
    git init -q "$checkout"
    git -C "$checkout" remote add origin "https://github.com/$repo"
    git -C "$checkout" fetch -q --depth 1 origin "$commit"
    git -C "$checkout" checkout -q FETCH_HEAD
  fi
  if [[ "$path" == *+* ]]; then
    mkdir -p "$dest/$name"
    IFS='+' read -ra items <<< "$path"
    for item in "${items[@]}"; do
      [[ -e "$checkout/$item" ]] && cp -r "$checkout/$item" "$dest/$name/"
    done
  else
    cp -r "$checkout/$path" "$dest/$name"
  fi
  echo "added  $name  ($repo@${commit:0:7})"
done
