#!/usr/bin/env bash
# Bump version across pyproject.toml, __init__.py (__version__), and package.json; commit, tag, push.
# Usage: scripts/release.sh 1.0.0-beta.1
# Requires: clean git index and worktree; clone with permission to push to origin.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "error: not inside a git repository." >&2
  exit 1
}
cd "${ROOT}"

if [[ "${#}" -ne 1 ]]; then
  echo "usage: $0 <semver>" >&2
  echo "  example: $0 1.0.0-beta.1" >&2
  exit 1
fi

VER_RAW="${1}"
VER="${VER_RAW#v}"
export RELEASE_VERSION="${VER}"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "error: working tree or index is not clean. Commit or stash changes before releasing." >&2
  exit 1
fi

# macOS ships Bash 3.2 — avoid mapfile/readarray (Bash 4+).
TO_ADD=()
while IFS= read -r _line; do
  [[ -n "${_line}" ]] || continue
  TO_ADD+=("${_line}")
done < <(RELEASE_VERSION="${VER}" python3 <<'PY'
import os
import re
import subprocess
import sys
from pathlib import Path

ver = os.environ.get("RELEASE_VERSION", "").strip()
if not ver:
    print("error: empty RELEASE_VERSION", file=sys.stderr)
    sys.exit(1)
if not re.fullmatch(
    r"(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){2}(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?",
    ver,
):
    print(
        f"error: version {ver!r} does not match expected pattern "
        r"(e.g. 1.2.3, 1.0.0-beta.1, 0.1.0-test).",
        file=sys.stderr,
    )
    sys.exit(1)

root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
os.chdir(root)
changed: list[str] = []


def bump_pyproject(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(r"(?m)^version = \"[^\"]*\"", f'version = "{ver}"', text)
    if n == 0 or new == text:
        return
    path.write_text(new, encoding="utf-8")
    changed.append(path.relative_to(root).as_posix())


def bump_init(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "__version__" not in text:
        return
    new = re.sub(
        r"^(__version__\s*=\s*\")[^\"]*(\")",
        lambda m: m.group(1) + ver + m.group(2),
        text,
        flags=re.M,
    )
    if new == text:
        return
    path.write_text(new, encoding="utf-8")
    changed.append(path.relative_to(root).as_posix())


def bump_package_json(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if '"version"' not in text:
        return
    new, n = re.subn(
        r"(\"version\"\s*:\s*\")[^\"]*(\")",
        lambda m: m.group(1) + ver + m.group(2),
        text,
        count=1,
    )
    if n == 0 or new == text:
        return
    path.write_text(new, encoding="utf-8")
    changed.append(path.relative_to(root).as_posix())


tracked = subprocess.check_output(["git", "ls-files", "-z"], text=False).split(b"\0")
for raw in tracked:
    if not raw:
        continue
    rel = raw.decode("utf-8", errors="surrogateescape")
    if "/node_modules/" in rel.replace("\\", "/"):
        continue
    path = root / rel
    if not path.is_file():
        continue
    if rel.endswith("pyproject.toml"):
        bump_pyproject(path)
    elif rel.endswith("package.json"):
        bump_package_json(path)
    elif rel.endswith("__init__.py"):
        bump_init(path)

if not changed:
    print("error: no files were modified (already at this version?).", file=sys.stderr)
    sys.exit(1)

for line in sorted(set(changed)):
    print(line)
PY
)

if [[ "${#TO_ADD[@]}" -eq 0 ]]; then
  echo "error: no paths to stage." >&2
  exit 1
fi

TAG="v${VER}"
if git rev-parse "${TAG}" >/dev/null 2>&1; then
  echo "error: tag ${TAG} already exists." >&2
  exit 1
fi

git add -- "${TO_ADD[@]}"
git commit -m "chore(release): ${TAG}"

git tag -a "${TAG}" -m "Release ${TAG}"

CURRENT_BRANCH="$(git branch --show-current)"
if [[ -z "${CURRENT_BRANCH}" ]]; then
  echo "error: detached HEAD; checkout a branch before releasing." >&2
  exit 1
fi

set +e
git push origin "refs/heads/${CURRENT_BRANCH}"
push_head=$?
git push origin "refs/tags/${TAG}"
push_tag=$?
set -e

if [[ "${push_head}" -ne 0 || "${push_tag}" -ne 0 ]]; then
  echo "error: git push failed (branch=${push_head}, tag=${push_tag})." >&2
  echo "  Fix the remote issue, then run: git push origin refs/heads/${CURRENT_BRANCH} && git push origin refs/tags/${TAG}" >&2
  exit 1
fi

echo "Released ${TAG}: committed, tagged, and pushed to origin."
