#!/usr/bin/env bash
# Sync repo docs/wiki/ mirror → github.com/pamu512/tarka/wiki (separate git repo).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WIKI_SRC="${ROOT}/docs/wiki"
TMP="${TMPDIR:-/tmp}/tarka.wiki-sync-$$"
REPO="${WIKI_REPO:-https://github.com/pamu512/tarka.wiki.git}"

if [[ ! -d "${WIKI_SRC}" ]]; then
  echo "sync-github-wiki: missing ${WIKI_SRC}" >&2
  exit 1
fi

cleanup() { rm -rf "${TMP}"; }
trap cleanup EXIT

echo "sync-github-wiki: clone ${REPO}"
git clone --depth 1 "${REPO}" "${TMP}"

echo "sync-github-wiki: copy pages (exclude README.md)"
find "${TMP}" -maxdepth 1 -name '*.md' ! -name 'README.md' -delete
for f in "${WIKI_SRC}"/*.md; do
  base="$(basename "$f")"
  [[ "$base" == "README.md" ]] && continue
  cp "$f" "${TMP}/${base}"
done

cd "${TMP}"
if git diff --quiet && git diff --cached --quiet; then
  echo "sync-github-wiki: no changes"
  exit 0
fi

git add -A
git status --short
git commit -m "docs: sync wiki from pamu512/tarka repo $(date -u +%Y-%m-%d)"

echo "sync-github-wiki: push"
git push origin HEAD

echo "sync-github-wiki: OK → ${REPO%.git}"
