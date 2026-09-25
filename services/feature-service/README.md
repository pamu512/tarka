# feature-service (source library)

Deploy surface: **signal-api** (`/features` endpoints) — see
[service-ports](../../docs/docs/guides/service-ports.md). This directory is the
source library signal-api mounts; it has no standalone compose service and no
Dockerfile. Source lives in `packages/feature-service/src` (library); this
directory keeps tests + docs only. One deploy surface, one job: signal-api.
