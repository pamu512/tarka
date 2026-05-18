#!/usr/bin/env bash
# Gate (Prompt 109): verify ``cases`` has evidence-locker columns after Alembic migration.
#
# Usage:
#   export DATABASE_URL="postgresql://fraud:fraud@localhost:5432/fraud"   # sync URL, no +asyncpg
#   ./deploy/scripts/gate_cases_evidence_columns_psql.sh
#
# Or from docker-compose.single.yml:
#   docker compose -f deploy/docker-compose.single.yml exec -T postgres \
#     psql -U fraud -d fraud -v ON_ERROR_STOP=1 -c "SELECT ..."
#
set -euo pipefail

_raw="${PSQL_URL:-${SHADOW_DATABASE_URL:-${DATABASE_URL:-}}}"
if [[ -z "${_raw}" ]]; then
  echo "Set PSQL_URL, SHADOW_DATABASE_URL, or DATABASE_URL (sync postgresql://…)" >&2
  exit 1
fi

# psql accepts postgresql://; strip SQLAlchemy drivers if present.
_url="${_raw//+asyncpg/}"
_url="${_url//+psycopg/}"
_url="${_url//postgresql+psycopg/postgresql}"

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is not on PATH" >&2
  exit 1
fi

_sql="SELECT count(*) FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'cases'
  AND column_name IN ('graph_snapshot', 'ai_trace', 'raw_signals_ref');"

_cnt="$(psql "${_url}" -v ON_ERROR_STOP=1 -t -A -c "${_sql}" | tr -d '[:space:]')"

if [[ "${_cnt}" != "3" ]]; then
  echo "Gate failed: expected 3 new columns on public.cases, got '${_cnt}'." >&2
  psql "${_url}" -v ON_ERROR_STOP=1 -c "\\d+ cases" >&2 || true
  exit 1
fi

_types_sql="SELECT column_name || ':' || data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'cases'
  AND column_name IN ('graph_snapshot', 'ai_trace', 'raw_signals_ref')
ORDER BY column_name;"
_types="$(psql "${_url}" -v ON_ERROR_STOP=1 -t -A -c "${_types_sql}")"

echo "${_types}" | grep -q '^ai_trace:text$' || {
  echo "Gate failed: ai_trace must be type text, got:" >&2
  echo "${_types}" >&2
  exit 1
}
echo "${_types}" | grep -q '^graph_snapshot:jsonb$' || {
  echo "Gate failed: graph_snapshot must be type jsonb, got:" >&2
  echo "${_types}" >&2
  exit 1
}
echo "${_types}" | grep -q '^raw_signals_ref:uuid$' || {
  echo "Gate failed: raw_signals_ref must be type uuid, got:" >&2
  echo "${_types}" >&2
  exit 1
}

echo "psql gate ok: cases.graph_snapshot (jsonb), ai_trace (text), raw_signals_ref (uuid)."
exit 0
