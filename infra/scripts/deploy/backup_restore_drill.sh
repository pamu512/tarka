#!/usr/bin/env bash
# SoR backup → restore drill: decisions / audit / packs / labels on external Postgres.
#
# Redis is ephemeral (velocity). AGE Hunt is a *volume* restore — do not pg_dump it
# (see scripts/oss/age_restore_drill.sh). This script never targets age-postgres.
#
# Modes:
#   --dry-run       (default) inventory + tool check; read-only table list if DATABASE_URL set
#   --docker-smoke  isolated Postgres in Docker; seed → dump → restore → verify
#   --live          dump source DATABASE_URL into TARKA_BACKUP_RESTORE_URL (scratch, must differ)
#
# Skip: TARKA_BACKUP_DRILL_SKIP=1
set -euo pipefail

MODE="dry-run"
PG_IMAGE="${TARKA_BACKUP_PG_IMAGE:-postgres:16}"
BACKUP_DIR="${TARKA_BACKUP_DIR:-/tmp/tarka-sor-backup-drill}"
CONFIRM="${TARKA_BACKUP_RESTORE_CONFIRM:-}"

# Beachhead SoR tables. Dump those that exist; skip the rest.
SOR_TABLES=(
  decision_audit
  vendor_integration_audit
  inference_logs
  rule_approvals
  backtest_runs
  fraud_rules
  engine_rules
  investigation_label_drafts
  leftover_promote_acks
  normalized_labels
  investigation_cases
)

usage() {
  cat <<'EOF'
Usage: backup_restore_drill.sh [--dry-run|--docker-smoke|--live]

  --dry-run       Print inventory and check tools. No dump/restore. (default)
  --docker-smoke  Isolated Docker Postgres: seed SoR tables, dump, restore, verify.
  --live          Dump DATABASE_URL → TARKA_BACKUP_RESTORE_URL (scratch DB).
                  Requires TARKA_BACKUP_RESTORE_CONFIRM=I_UNDERSTAND.

Env:
  DATABASE_URL                 Source (postgresql://…; +asyncpg / +psycopg stripped)
  TARKA_BACKUP_RESTORE_URL     Scratch target (must differ from source)
  TARKA_BACKUP_DIR             Backup artifact directory
  DECISION_LOG_PATH            Optional object export (JSONL)
  PACK_GITOPS_EXPORT_PATH      Optional pack promote export (JSONL)
  TARKA_BACKUP_DRILL_SKIP=1    Exit 0 without work
EOF
}

normalize_pg_url() {
  local raw="${1:-}"
  raw="${raw//+asyncpg/}"
  raw="${raw//+psycopg2/}"
  raw="${raw//+psycopg/}"
  raw="${raw//postgresql+psycopg/postgresql}"
  printf '%s' "$raw"
}

url_fingerprint() {
  # Host + port + dbname only — userinfo ignored so the same cluster with
  # different passwords still collides as "same target".
  python3 -c '
import sys
from urllib.parse import urlparse
u = urlparse(sys.argv[1])
db = (u.path or "").lstrip("/")
host = (u.hostname or "").lower()
port = u.port or 5432
print(f"{host}:{port}/{db}")
' "$1"
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

if [[ "${TARKA_BACKUP_DRILL_SKIP:-}" == "1" ]]; then
  echo "SoR backup drill skipped (TARKA_BACKUP_DRILL_SKIP=1)"
  exit 0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) MODE="dry-run"; shift ;;
    --docker-smoke) MODE="docker-smoke"; shift ;;
    --live) MODE="live"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

echo "=== Tarka SoR backup/restore drill (${MODE}) ==="
echo "SoR tables: ${SOR_TABLES[*]}"
echo "Redis: ephemeral velocity — not dumped. Empty Redis after restore is expected."
echo "AGE Hunt: volume restore only (scripts/oss/age_restore_drill.sh). Not in this dump."
echo "Object export: DECISION_LOG_PATH / PACK_GITOPS_EXPORT_PATH if set and present."
echo "Out: Tarka-operated backup SaaS."

copy_object_exports() {
  local dest="$1/object-export"
  mkdir -p "$dest"
  local copied=0
  if [[ -n "${DECISION_LOG_PATH:-}" && -f "${DECISION_LOG_PATH}" ]]; then
    cp -a "${DECISION_LOG_PATH}" "$dest/decision-log.jsonl"
    copied=1
    echo "object_export copied DECISION_LOG_PATH"
  fi
  if [[ -n "${PACK_GITOPS_EXPORT_PATH:-}" && -f "${PACK_GITOPS_EXPORT_PATH}" ]]; then
    cp -a "${PACK_GITOPS_EXPORT_PATH}" "$dest/promote_export.jsonl"
    copied=1
    echo "object_export copied PACK_GITOPS_EXPORT_PATH"
  fi
  if [[ "$copied" -eq 0 ]]; then
    echo "object_export skipped (paths unset or missing — plane off)"
  fi
}

verify_object_exports() {
  local dest="$1/object-export"
  if [[ -n "${DECISION_LOG_PATH:-}" && -f "${DECISION_LOG_PATH}" ]]; then
    cmp -s "${DECISION_LOG_PATH}" "$dest/decision-log.jsonl" || {
      echo "object_export mismatch: decision-log.jsonl" >&2
      return 1
    }
  fi
  if [[ -n "${PACK_GITOPS_EXPORT_PATH:-}" && -f "${PACK_GITOPS_EXPORT_PATH}" ]]; then
    cmp -s "${PACK_GITOPS_EXPORT_PATH}" "$dest/promote_export.jsonl" || {
      echo "object_export mismatch: promote_export.jsonl" >&2
      return 1
    }
  fi
}

dry_run() {
  echo "dry-run: no dump, no restore, no DROP."
  local tools=()
  have_cmd psql && tools+=(psql)
  have_cmd pg_dump && tools+=(pg_dump)
  have_cmd pg_restore && tools+=(pg_restore)
  have_cmd docker && tools+=(docker)
  echo "tools_on_path: ${tools[*]:-none}"
  if [[ ${#tools[@]} -eq 0 ]]; then
    echo "WARN: neither psql/pg_dump nor docker on PATH. --live/--docker-smoke will fail." >&2
  fi

  local src
  src="$(normalize_pg_url "${DATABASE_URL:-}")"
  if [[ -z "$src" ]]; then
    echo "DATABASE_URL unset — table inventory skipped (ok for CI dry-run)."
    echo "dry-run OK"
    return 0
  fi
  if ! have_cmd psql; then
    echo "DATABASE_URL set but psql missing — cannot list tables. Still dry-run OK."
    echo "dry-run OK"
    return 0
  fi
  echo "listing SoR tables on source (read-only)…"
  local t present=0 missing=0
  for t in "${SOR_TABLES[@]}"; do
    local cnt
    cnt="$(psql "$src" -v ON_ERROR_STOP=1 -t -A -c \
      "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='${t}';" \
      2>/dev/null | tr -d '[:space:]' || true)"
    if [[ "$cnt" == "1" ]]; then
      echo "  present  ${t}"
      present=$((present + 1))
    else
      echo "  absent   ${t}"
      missing=$((missing + 1))
    fi
  done
  echo "present=${present} absent=${missing} (absent is ok on evaluate-only)"
  echo "dry-run OK"
}

existing_tables_sql() {
  # Prints table names that exist in public among SOR_TABLES, one per line.
  local url="$1"
  local in_list=""
  local t
  for t in "${SOR_TABLES[@]}"; do
    [[ -n "$in_list" ]] && in_list+=","
    in_list+="'${t}'"
  done
  psql "$url" -v ON_ERROR_STOP=1 -t -A -c \
    "SELECT table_name FROM information_schema.tables
     WHERE table_schema='public' AND table_name IN (${in_list})
     ORDER BY table_name;"
}

dump_and_restore() {
  local src="$1"
  local dst="$2"
  mkdir -p "$BACKUP_DIR"
  local dump_file="${BACKUP_DIR}/sor.dump"
  rm -f "$dump_file"

  mapfile -t found < <(existing_tables_sql "$src")
  if [[ ${#found[@]} -eq 0 || -z "${found[0]:-}" ]]; then
    echo "no SoR tables on source — nothing to dump" >&2
    return 1
  fi
  echo "dumping: ${found[*]}"
  local args=()
  local t
  for t in "${found[@]}"; do
    [[ -z "$t" ]] && continue
    args+=(-t "public.${t}")
  done
  pg_dump "$src" --format=custom --no-owner --no-acl "${args[@]}" -f "$dump_file"
  copy_object_exports "$BACKUP_DIR"

  echo "restoring into scratch…"
  pg_restore --no-owner --no-acl --dbname="$dst" "$dump_file"

  echo "verifying row counts…"
  for t in "${found[@]}"; do
    [[ -z "$t" ]] && continue
    local src_n dst_n
    src_n="$(psql "$src" -v ON_ERROR_STOP=1 -t -A -c "SELECT count(*) FROM public.${t};" | tr -d '[:space:]')"
    dst_n="$(psql "$dst" -v ON_ERROR_STOP=1 -t -A -c "SELECT count(*) FROM public.${t};" | tr -d '[:space:]')"
    echo "  ${t} source=${src_n} restore=${dst_n}"
    if [[ "$src_n" != "$dst_n" ]]; then
      echo "row count mismatch on ${t}" >&2
      return 1
    fi
  done
  verify_object_exports "$BACKUP_DIR"
  echo "SoR restore OK (row counts match for dumped tables)"
}

live_mode() {
  if [[ "$CONFIRM" != "I_UNDERSTAND" ]]; then
    echo "set TARKA_BACKUP_RESTORE_CONFIRM=I_UNDERSTAND for --live" >&2
    exit 2
  fi
  local src dst
  src="$(normalize_pg_url "${DATABASE_URL:-}")"
  dst="$(normalize_pg_url "${TARKA_BACKUP_RESTORE_URL:-}")"
  if [[ -z "$src" || -z "$dst" ]]; then
    echo "DATABASE_URL and TARKA_BACKUP_RESTORE_URL required for --live" >&2
    exit 2
  fi
  if [[ "$(url_fingerprint "$src")" == "$(url_fingerprint "$dst")" ]]; then
    echo "refuse: restore URL fingerprints as the source (scratch DB required)" >&2
    exit 2
  fi
  if ! have_cmd pg_dump || ! have_cmd pg_restore || ! have_cmd psql; then
    echo "pg_dump, pg_restore, and psql required on PATH for --live" >&2
    exit 1
  fi
  echo "source=$(url_fingerprint "$src") target=$(url_fingerprint "$dst")"
  dump_and_restore "$src" "$dst"
}

docker_smoke() {
  if ! have_cmd docker; then
    echo "docker required for --docker-smoke" >&2
    exit 1
  fi
  local net="tarka-sor-backup-net"
  local src_c="tarka-sor-backup-src"
  local dst_c="tarka-sor-backup-dst"
  local user_name="${TARKA_BACKUP_PGUSER:-fraud}"
  local pass="${TARKA_BACKUP_PGPASSWORD:-fraud}"
  local db="${TARKA_BACKUP_PGDATABASE:-fraud}"

  cleanup() {
    docker rm -f "$src_c" "$dst_c" >/dev/null 2>&1 || true
    docker network rm "$net" >/dev/null 2>&1 || true
  }
  trap cleanup EXIT
  cleanup
  docker network create "$net" >/dev/null

  docker run -d --name "$src_c" --network "$net" \
    -e POSTGRES_USER="$user_name" \
    -e POSTGRES_PASSWORD="$pass" \
    -e POSTGRES_DB="$db" \
    "$PG_IMAGE" >/dev/null
  docker run -d --name "$dst_c" --network "$net" \
    -e POSTGRES_USER="$user_name" \
    -e POSTGRES_PASSWORD="$pass" \
    -e POSTGRES_DB="$db" \
    "$PG_IMAGE" >/dev/null

  wait_ready() {
    local c="$1"
    local i
    for i in $(seq 1 60); do
      if docker exec "$c" pg_isready -U "$user_name" -d "$db" >/dev/null 2>&1; then
        return 0
      fi
      sleep 1
    done
    echo "postgres not ready: $c" >&2
    return 1
  }
  echo "waiting for smoke Postgres…"
  wait_ready "$src_c"
  wait_ready "$dst_c"

  local seed
  seed=$(cat <<'SQL'
CREATE TABLE decision_audit (
  id uuid PRIMARY KEY,
  trace_id uuid UNIQUE NOT NULL,
  tenant_id text NOT NULL,
  entity_id text NOT NULL,
  event_type text NOT NULL,
  decision text NOT NULL,
  score double precision NOT NULL
);
CREATE TABLE rule_approvals (
  id uuid PRIMARY KEY,
  pack_name text NOT NULL,
  fingerprint_sha256 text NOT NULL,
  actor_user_id text NOT NULL,
  audit_token text UNIQUE NOT NULL
);
CREATE TABLE investigation_label_drafts (
  id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  analyst_id text NOT NULL,
  y_label text NOT NULL
);
CREATE TABLE leftover_promote_acks (
  id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  draft_id text NOT NULL,
  acked_by text NOT NULL
);
INSERT INTO decision_audit VALUES (
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222222',
  'tenant-smoke', 'entity-1', 'payment', 'REVIEW', 61.0
);
INSERT INTO rule_approvals VALUES (
  '33333333-3333-3333-3333-333333333333',
  'smoke-pack', repeat('a', 64), 'analyst-1', 'tok-smoke'
);
INSERT INTO investigation_label_drafts VALUES (
  '44444444-4444-4444-4444-444444444444',
  'tenant-smoke', 'analyst-1', 'fraud'
);
INSERT INTO leftover_promote_acks VALUES (
  '55555555-5555-5555-5555-555555555555',
  'tenant-smoke', 'draft-1', 'analyst-1'
);
SQL
)
  docker exec -i "$src_c" psql -U "$user_name" -d "$db" -v ON_ERROR_STOP=1 <<<"$seed"

  mkdir -p "$BACKUP_DIR"
  local dump_file="${BACKUP_DIR}/sor.dump"
  rm -f "$dump_file"
  docker exec "$src_c" pg_dump -U "$user_name" -d "$db" --format=custom --no-owner --no-acl \
    -t public.decision_audit \
    -t public.rule_approvals \
    -t public.investigation_label_drafts \
    -t public.leftover_promote_acks \
    -f /tmp/sor.dump
  docker cp "${src_c}:/tmp/sor.dump" "$dump_file"
  docker cp "$dump_file" "${dst_c}:/tmp/sor.dump"
  docker exec "$dst_c" pg_restore --no-owner --no-acl -U "$user_name" -d "$db" /tmp/sor.dump

  local obj_dir="${BACKUP_DIR}/object-export"
  mkdir -p "$obj_dir"
  printf '%s\n' '{"schema_id":"tarka.decision_log/v1","trace_id":"22222222-2222-2222-2222-222222222222"}' \
    >"${obj_dir}/decision-log.jsonl"
  printf '%s\n' '{"schema_id":"tarka.pack_promote_export/v1","pack":"smoke-pack"}' \
    >"${obj_dir}/promote_export.jsonl"

  local hop
  hop="$(docker exec "$dst_c" psql -U "$user_name" -d "$db" -t -A -v ON_ERROR_STOP=1 -c \
    "SELECT decision || ':' || score FROM decision_audit WHERE trace_id='22222222-2222-2222-2222-222222222222';")"
  local packs labels acks
  packs="$(docker exec "$dst_c" psql -U "$user_name" -d "$db" -t -A -c "SELECT count(*) FROM rule_approvals;" | tr -d '[:space:]')"
  labels="$(docker exec "$dst_c" psql -U "$user_name" -d "$db" -t -A -c "SELECT count(*) FROM investigation_label_drafts;" | tr -d '[:space:]')"
  acks="$(docker exec "$dst_c" psql -U "$user_name" -d "$db" -t -A -c "SELECT count(*) FROM leftover_promote_acks;" | tr -d '[:space:]')"
  echo "restore_probe decision=${hop} packs=${packs} labels=${labels} acks=${acks}"
  if [[ "$hop" != "REVIEW:61" || "$packs" != "1" || "$labels" != "1" || "$acks" != "1" ]]; then
    echo "docker-smoke failed: SoR identity missing after restore" >&2
    exit 1
  fi
  if [[ ! -f "${obj_dir}/decision-log.jsonl" || ! -f "${obj_dir}/promote_export.jsonl" ]]; then
    echo "docker-smoke failed: object export missing" >&2
    exit 1
  fi
  echo "SoR backup/restore docker-smoke OK"
}

case "$MODE" in
  dry-run) dry_run ;;
  live) live_mode ;;
  docker-smoke) docker_smoke ;;
  *) echo "bad mode: $MODE" >&2; exit 2 ;;
esac
