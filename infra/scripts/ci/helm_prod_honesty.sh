#!/usr/bin/env bash
# G1 production Helm honesty gate (beachhead VPC CE-shaped).
# Fails if a production-labeled preset would run decisions/audit on sqlite or
# durable emptyDir, enable in-cluster Postgres for core, or ship chart-default
# password "fraud" in the render.
#
# Documented emptyDir exceptions (non-durable / not core SoR):
#   investigation-agent-data — postgres-mode scratch (stores are on buyer PG)
#   location-data            — signal-api geo cache, not decision/audit/pack/label
#   data on age-postgres     — Hunt sidecar, not core DATABASE_URL
#   data on nats             — broker ephemeral
#
# Empty image digest may warn (G2). This script does not fail on empty digest.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CHART="$ROOT_DIR/infra/deploy/helm/fraud-stack"
GEN="$ROOT_DIR/infra/scripts/deploy/generate_cloud_values.py"
BAD_FIXTURE_DIR="$ROOT_DIR/infra/scripts/ci/fixtures/helm_prod_honesty"

usage() {
  cat <<'EOF'
Usage:
  helm_prod_honesty.sh --self-check
  helm_prod_honesty.sh --manifest FILE [--expect-fail]
  helm_prod_honesty.sh --preset prod-on-k8s [--preset enterprise-desk-on-k8s]
EOF
}

scan_manifest() {
  local manifest="$1"
  python3 - "$manifest" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
errors: list[str] = []

# sqlite connection strings / file paths / TREND durable sqlite
if re.search(r"sqlite(\+|://|:)|[A-Za-z0-9_./-]+\.sqlite3?", text, re.I):
    errors.append("sqlite connection string or sqlite file path")
if re.search(r"name:\s+TREND_AGENT_(DATA_DIR|DB_NAME)\b", text):
    errors.append("TREND sqlite durable path env (TREND_AGENT_DATA_DIR / TREND_AGENT_DB_NAME)")
if re.search(
    r"name:\s+INVESTIGATION_STORE\n\s+value:\s+[\"']?sqlite[\"']?",
    text,
):
    errors.append("INVESTIGATION_STORE=sqlite")

# chart-default password fraud (user name "fraud" in dummy URLs is allowed)
if re.search(r"name:\s+POSTGRES_PASSWORD\n\s+value:\s+[\"']?fraud[\"']?", text):
    errors.append("POSTGRES_PASSWORD uses chart-default 'fraud'")
if re.search(r":fraud@", text):
    errors.append("connection string embeds password 'fraud'")

# Allowed emptyDir volume names when the owning Deployment is not core postgres.
# ponytail: name allow-list; upgrade is a typed volume policy in the chart.
_ALLOW_VOL = {
    "investigation-agent-data",
    "location-data",
}

def _docs(raw: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    for line in raw.splitlines(True):
        if line.startswith("---") and cur:
            parts.append("".join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        parts.append("".join(cur))
    return parts


def _kind_name(doc: str) -> tuple[str, str]:
    kind = ""
    in_meta = False
    for line in doc.splitlines():
        if line.startswith("kind:"):
            kind = line.split(":", 1)[1].strip()
        if line.startswith("metadata:"):
            in_meta = True
        elif in_meta and line.startswith("  name:"):
            return kind, line.split(":", 1)[1].strip()
        elif in_meta and line.startswith("spec:"):
            in_meta = False
    return kind, ""


def _empty_dir_volumes(doc: str) -> list[str]:
    names: list[str] = []
    pending = ""
    for line in doc.splitlines():
        m = re.match(r"\s+-\s+name:\s+(\S+)", line)
        if m:
            pending = m.group(1).strip().strip("\"'")
        if re.search(r"emptyDir:\s*(\{\}|)", line) and pending:
            names.append(pending)
            pending = ""
    return names


_DURABLE_VOL = re.compile(r"(decision|audit|pack|label)", re.I)

for doc in _docs(text):
    kind, name = _kind_name(doc)
    if kind == "Deployment" and name.endswith("-postgres") and "age-postgres" not in name:
        errors.append(f"in-cluster core Postgres Deployment {name}")
    if kind != "Deployment":
        continue
    hunt = "age-postgres" in name
    nats = name.endswith("-nats") or name.endswith("-nats-")
    for vol in _empty_dir_volumes(doc):
        if _DURABLE_VOL.search(vol):
            errors.append(f"emptyDir on durable volume {vol!r} in {name}")
            continue
        if vol in _ALLOW_VOL:
            continue
        if vol == "data" and (hunt or nats):
            # Hunt sidecar / broker ephemeral — not core decision/audit SoR
            continue
        if vol == "data" and name.endswith("-postgres") and "age-postgres" not in name:
            errors.append(f"emptyDir on in-cluster Postgres data in {name}")
            continue
        if vol == "data":
            errors.append(f"emptyDir on volume 'data' in {name} (durable unless documented exception)")
            continue
        errors.append(f"emptyDir on undocumented volume {vol!r} in {name}")

# core DATABASE_URL must not target in-cluster chart postgres
for m in re.finditer(r"name:\s+DATABASE_URL\n\s+value:\s+\"([^\"]+)\"", text):
    url = m.group(1)
    if "-postgres:" in url and "age-postgres" not in url:
        errors.append(f"DATABASE_URL points at in-cluster chart postgres ({url})")

# G2: empty digest is allowed; warn if prod images are tag-only.
if re.search(r"image:\s+\".*:1\.3\.0-beta\"", text) and "@sha256:" not in text:
    print(
        f"WARN: {path}: image tags without digest (G2 will enforce pins)",
        file=sys.stderr,
    )

if errors:
    # de-dupe while keeping order
    seen: set[str] = set()
    uniq: list[str] = []
    for err in errors:
        if err not in seen:
            seen.add(err)
            uniq.append(err)
    for err in uniq:
        print(f"FAIL: {path}: {err}", file=sys.stderr)
    sys.exit(1)
print(f"OK: honesty scan {path}")
PY
}

render_preset() {
  local preset="$1"
  local out_values out_manifest
  out_values="$(mktemp)"
  out_manifest="$(mktemp)"
  if [[ ! -x "$(command -v helm || true)" ]]; then
    echo "FAIL: helm is required to render $preset" >&2
    return 2
  fi
  if [[ ! -f "$GEN" ]]; then
    echo "FAIL: missing $GEN" >&2
    return 2
  fi
  python3 "$GEN" \
    --preset "$preset" \
    --image-registry registry.example.com/tarka \
    --db-url 'postgresql+asyncpg://fraud:pw@db.internal:5432/fraud' \
    --redis-url 'rediss://elasticache:6379/0' \
    --output "$out_values" \
    >/dev/null
  local extra=()
  if [[ "$preset" == "enterprise-desk-on-k8s" ]]; then
    extra+=(--set global.appSecretsName=tarka-app-secrets)
  fi
  helm template tarka "$CHART" -f "$out_values" "${extra[@]}" >"$out_manifest"
  echo "$out_manifest"
}

SELF_CHECK=0
EXPECT_FAIL=0
MANIFESTS=()
PRESETS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --self-check)
      SELF_CHECK=1
      shift
      ;;
    --expect-fail)
      EXPECT_FAIL=1
      shift
      ;;
    --manifest)
      [[ $# -ge 2 ]] || { echo "FAIL: --manifest needs a file" >&2; exit 2; }
      MANIFESTS+=("$2")
      shift 2
      ;;
    --preset)
      [[ $# -ge 2 ]] || { echo "FAIL: --preset needs a name" >&2; exit 2; }
      PRESETS+=("$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "FAIL: unknown arg $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$SELF_CHECK" -eq 1 ]]; then
  if [[ ! -d "$BAD_FIXTURE_DIR" ]]; then
    echo "FAIL: missing negative fixture dir $BAD_FIXTURE_DIR" >&2
    exit 2
  fi
  # One fixture per fail class. A single OR-blob would stay green if one check dies.
  declare -A EXPECTED_FAIL=(
    [bad_sqlite_url]="sqlite connection string"
    [bad_trend_path]="TREND sqlite durable path"
    [bad_investigation_store]="INVESTIGATION_STORE=sqlite"
    [bad_emptydir_durable]="emptyDir on durable volume"
    [bad_incluster_postgres]="in-cluster core Postgres Deployment"
    [bad_password_fraud]="password"
  )
  for class in bad_sqlite_url bad_trend_path bad_investigation_store \
    bad_emptydir_durable bad_incluster_postgres bad_password_fraud; do
    fixture="$BAD_FIXTURE_DIR/${class}.manifest.yaml"
    if [[ ! -f "$fixture" ]]; then
      echo "FAIL: missing per-class fixture $fixture" >&2
      exit 2
    fi
    echo "self-check: $class must fail"
    errf="$(mktemp)"
    if scan_manifest "$fixture" 2>"$errf"; then
      echo "FAIL: $class passed honesty scan (gate is blind)" >&2
      cat "$errf" >&2
      exit 1
    fi
    if ! grep -q "${EXPECTED_FAIL[$class]}" "$errf"; then
      echo "FAIL: $class failed but not for '${EXPECTED_FAIL[$class]}'" >&2
      cat "$errf" >&2
      exit 1
    fi
    echo "OK: $class failed as required"
  done
  echo "self-check: prod-on-k8s must pass"
  prod_manifest="$(render_preset prod-on-k8s)"
  scan_manifest "$prod_manifest"
  echo "self-check: enterprise-desk-on-k8s must pass"
  desk_manifest="$(render_preset enterprise-desk-on-k8s)"
  scan_manifest "$desk_manifest"
  echo "OK: helm_prod_honesty self-check passed"
  exit 0
fi

if [[ ${#MANIFESTS[@]} -eq 0 && ${#PRESETS[@]} -eq 0 ]]; then
  usage >&2
  exit 2
fi

status=0
for preset in "${PRESETS[@]+"${PRESETS[@]}"}"; do
  [[ -n "$preset" ]] || continue
  manifest="$(render_preset "$preset")"
  if ! scan_manifest "$manifest"; then
    status=1
  fi
done
for manifest in "${MANIFESTS[@]+"${MANIFESTS[@]}"}"; do
  [[ -n "$manifest" ]] || continue
  if scan_manifest "$manifest"; then
    if [[ "$EXPECT_FAIL" -eq 1 ]]; then
      echo "FAIL: expected $manifest to fail honesty scan" >&2
      status=1
    fi
  else
    if [[ "$EXPECT_FAIL" -eq 1 ]]; then
      echo "OK: $manifest failed as expected"
    else
      status=1
    fi
  fi
done
exit "$status"
