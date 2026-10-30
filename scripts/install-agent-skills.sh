#!/usr/bin/env bash
# Install the agent skills used to build ARIA, pinned to the reviewed commits in
# .claude/skills.lock.tsv, into ~/.claude/skills (or $CLAUDE_SKILLS_DIR).
#
# Each repository is fetched at its pinned commit into a temporary directory and only the listed
# skill folder is copied. A path of the form "a+b+c" copies just those items from the repository
# root (used when a skill repository also holds CI scripts that are not part of the skill).
# Every installed skill gets a .aria-skill-source marker recording repo, commit and path, so a
# changed pin is detected and reinstalled. A skill folder without a marker that differs from the
# pinned version is left alone: it may be the user's own copy.
#
# Usage: install-agent-skills.sh          install missing or outdated skills
#        install-agent-skills.sh --check  exit 1 if any skill is missing or outdated
set -euo pipefail

lock="$(cd "$(dirname "$0")/.." && pwd)/.claude/skills.lock.tsv"
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
mode="${1:-install}"
marker=".aria-skill-source"
mkdir -p "$dest"

valid_name() { [[ "$1" =~ ^[a-z0-9][a-z0-9-]*$ ]]; }

if [[ "$mode" == "--check" ]]; then
  missing=0
  while IFS=$'\t' read -r name repo commit path; do
    [[ -z "$name" ]] && continue
    want="$repo@$commit $path"
    if [[ ! -d "$dest/$name" ]]; then
      echo "missing  $name"
      missing=1
    elif [[ -f "$dest/$name/$marker" && "$(cat "$dest/$name/$marker")" != "$want" ]]; then
      echo "outdated $name"
      missing=1
    fi
  done < <(tail -n +2 "$lock")
  exit "$missing"
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fetch() {  # fetch() repo commit -> prints the checkout directory
  local checkout="$work/${1//\//_}-${2:0:12}"
  if [[ ! -d "$checkout/.git" ]]; then
    git init -q "$checkout"
    git -C "$checkout" remote add origin "https://github.com/$1"
    git -C "$checkout" fetch -q --depth 1 origin "$2"
    git -C "$checkout" checkout -q FETCH_HEAD
  fi
  echo "$checkout"
}

while IFS=$'\t' read -r name repo commit path; do
  [[ -z "$name" ]] && continue
  if ! valid_name "$name"; then
    echo "error    invalid skill name in lock file: $name" >&2
    exit 1
  fi
  target="$dest/$name"
  want="$repo@$commit $path"
  if [[ -f "$target/$marker" && "$(cat "$target/$marker")" == "$want" ]]; then
    echo "ok       $name"
    continue
  fi
  checkout="$(fetch "$repo" "$commit")"
  stage="$work/stage/$name"
  mkdir -p "$work/stage"
  if [[ "$path" == *+* ]]; then
    mkdir -p "$stage"
    IFS='+' read -ra items <<< "$path"
    for item in "${items[@]}"; do
      [[ -e "$checkout/$item" ]] && cp -r "$checkout/$item" "$stage/"
    done
  else
    cp -r "$checkout/$path" "$stage"
  fi
  if [[ -e "$target" ]]; then
    if [[ ! -f "$target/$marker" ]] && ! diff -rq "$stage" "$target" > /dev/null 2>&1; then
      echo "kept     $name (an unmanaged copy that differs from the pin; not overwritten)"
      continue
    fi
    rm -rf "$target"
  fi
  mv "$stage" "$target"
  echo "$want" > "$target/$marker"
  echo "added    $name  ($repo@${commit:0:7})"
done < <(tail -n +2 "$lock")
