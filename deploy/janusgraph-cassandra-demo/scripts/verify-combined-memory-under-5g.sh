#!/usr/bin/env bash
# Gate check (Prompt 81): combined memory usage of Cassandra + JanusGraph demo containers < 5 GiB.
#
# Prerequisites: stack is up (`docker compose … up -d`) and containers are named
# `jcd-cassandra` and `jcd-janusgraph` (see ../docker-compose.yml).
#
# Usage:
#   ./deploy/janusgraph-cassandra-demo/scripts/verify-combined-memory-under-5g.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found in PATH" >&2
  exit 2
fi

python3 <<'PY'
import re
import subprocess
import sys

containers = ("jcd-cassandra", "jcd-janusgraph")
# Example: "441.6MiB / 7.65GiB" — use the in-use value before "/"
suffix_re = re.compile(r"^([\d.]+)\s*([KMGT]iB|B)$", re.IGNORECASE)


def parse_to_bytes(chunk: str) -> int:
    s = chunk.strip()
    m = suffix_re.match(s)
    if not m:
        raise ValueError(f"unrecognized mem chunk: {chunk!r}")
    val = float(m.group(1))
    u = m.group(2).lower()
    if u == "b":
        return int(val)
    mult = {
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
    }.get(u, None)
    if mult is None:
        raise ValueError(f"unknown unit in {chunk!r}")
    return int(val * mult)


def mem_usage_bytes(name: str) -> int:
    out = subprocess.check_output(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", name],
        text=True,
    ).strip()
    if not out or "/" not in out:
        raise RuntimeError(f"unexpected stats for {name}: {out!r}")
    left = out.split("/", 1)[0].strip()
    return parse_to_bytes(left)


total = 0
rows = []
for c in containers:
    try:
        b = mem_usage_bytes(c)
    except subprocess.CalledProcessError as exc:
        print(f"error: is container {c} running? ({exc})", file=sys.stderr)
        sys.exit(3)
    rows.append((c, b))
    total += b

limit = 5 * 1024 * 1024 * 1024
for c, b in rows:
    print(f"{c}\t{b}\tbytes ({b / (1024**2):.1f} MiB)")
print(f"combined\t{total}\tbytes ({total / (1024**3):.3f} GiB)")
print(f"limit\t{limit}\tbytes (5 GiB)")

if total > limit:
    print("FAIL: combined memory exceeds 5 GiB", file=sys.stderr)
    sys.exit(1)
print("PASS: combined memory is at or under 5 GiB")
PY
