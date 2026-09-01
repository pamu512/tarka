#!/usr/bin/env bash
# AGE Hunt restore drill: seed Person→Device hop, volume backup, restore, prove hop.
#
# Apache AGE encodes catalog OIDs into graphids — logical pg_dump/pg_restore breaks
# hops ("graph with oid N does not exist"). Tarka-shipped AGE uses filesystem/volume
# restore (same class as pg_basebackup). This drill proves that path.
#
# CI / local: needs docker. Skip with AGE_RESTORE_DRILL_SKIP=1.
set -euo pipefail

IMAGE="${AGE_IMAGE:-apache/age:release_PG16_1.6.0}"
NET="tarka-age-restore-net"
SRC="tarka-age-restore-src"
DST="tarka-age-restore-dst"
VOL_SRC="tarka-age-restore-vol-src"
VOL_DST="tarka-age-restore-vol-dst"
ARCHIVE="${AGE_RESTORE_ARCHIVE:-/tmp/tarka-age-restore-data.tgz}"
USER_NAME="${AGE_PGUSER:-fraud}"
PASS="${AGE_PGPASSWORD:-fraud}"
DB="${AGE_PGDATABASE:-fraud}"

if [[ "${AGE_RESTORE_DRILL_SKIP:-}" == "1" ]]; then
  echo "AGE restore drill skipped (AGE_RESTORE_DRILL_SKIP=1)"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker required for AGE restore drill" >&2
  exit 1
fi

cleanup() {
  docker rm -f "$SRC" "$DST" >/dev/null 2>&1 || true
  docker volume rm -f "$VOL_SRC" "$VOL_DST" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
docker network create "$NET" >/dev/null
docker volume create "$VOL_SRC" >/dev/null

docker run -d --name "$SRC" --network "$NET" \
  -v "${VOL_SRC}:/var/lib/postgresql/data" \
  -e POSTGRES_USER="$USER_NAME" \
  -e POSTGRES_PASSWORD="$PASS" \
  -e POSTGRES_DB="$DB" \
  "$IMAGE" \
  postgres -c shared_preload_libraries=age >/dev/null

echo "waiting for AGE source..."
for _ in $(seq 1 60); do
  if docker exec "$SRC" pg_isready -U "$USER_NAME" -d "$DB" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$SRC" pg_isready -U "$USER_NAME" -d "$DB" >/dev/null

seed_sql=$(cat <<'SQL'
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('tarka');
SELECT * FROM cypher('tarka', $$
  CREATE (p:Person {tenant_id: 'demo', external_id: 'person-1', name: 'Alice'})
  CREATE (d:Device {tenant_id: 'demo', external_id: 'device-1'})
  CREATE (p)-[:USES_DEVICE]->(d)
  RETURN p.external_id, d.external_id
$$) AS (person agtype, device agtype);
SQL
)
docker exec -i "$SRC" psql -U "$USER_NAME" -d "$DB" -v ON_ERROR_STOP=1 <<<"$seed_sql"

# Checkpoint and stop cleanly before volume snapshot.
docker exec "$SRC" psql -U "$USER_NAME" -d "$DB" -c "CHECKPOINT;"
docker stop "$SRC" >/dev/null

rm -f "$ARCHIVE"
docker run --rm \
  -v "${VOL_SRC}:/from:ro" \
  -v "$(dirname "$ARCHIVE"):/out" \
  alpine:3.20 \
  tar czf "/out/$(basename "$ARCHIVE")" -C /from .

docker volume create "$VOL_DST" >/dev/null
docker run --rm \
  -v "${VOL_DST}:/to" \
  -v "$(dirname "$ARCHIVE"):/in:ro" \
  alpine:3.20 \
  tar xzf "/in/$(basename "$ARCHIVE")" -C /to

docker run -d --name "$DST" --network "$NET" \
  -v "${VOL_DST}:/var/lib/postgresql/data" \
  -e POSTGRES_USER="$USER_NAME" \
  -e POSTGRES_PASSWORD="$PASS" \
  -e POSTGRES_DB="$DB" \
  "$IMAGE" \
  postgres -c shared_preload_libraries=age >/dev/null

echo "waiting for AGE restore target..."
for _ in $(seq 1 60); do
  if docker exec "$DST" pg_isready -U "$USER_NAME" -d "$DB" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$DST" pg_isready -U "$USER_NAME" -d "$DB" >/dev/null

hop_sql=$(cat <<'SQL'
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT * FROM cypher('tarka', $$
  MATCH (p:Person {external_id: 'person-1'})-[:USES_DEVICE]->(d:Device)
  RETURN p.external_id, d.external_id
$$) AS (person agtype, device agtype);
SQL
)
out="$(docker exec -i "$DST" psql -U "$USER_NAME" -d "$DB" -t -A -v ON_ERROR_STOP=1 <<<"$hop_sql")"
echo "hop_result=$out"
if [[ "$out" != *"person-1"* ]] || [[ "$out" != *"device-1"* ]]; then
  echo "AGE restore drill failed: Person hop missing after volume restore" >&2
  exit 1
fi
echo "AGE restore drill OK (Person→Device hop present after volume restore)"
