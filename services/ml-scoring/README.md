# ml-scoring (source library)

Deploy surface: **signal-api** (`/ml` endpoints) — see
[service-ports](../../docs/docs/guides/service-ports.md). This directory is the
source library signal-api mounts; it has no standalone compose service and no
Dockerfile. Source lives in `packages/ml-scoring/src` (library); this
directory keeps tests, models, rules, and training data. One deploy surface,
one job: signal-api.
