# Operations

| Topic | Pointer |
|-------|---------|
| Compose profiles / SRE | [`docs/docs/operations/sre-compose-profiles.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/operations/sre-compose-profiles.md) |
| Desk | `docker-compose.lite.yml` + `docker-compose.fraud-desk.yml` |
| Graph + decision graph | `docker-compose.graph-wire.yml` + `--profile graph` |
| Ingest + trend | `docker-compose.v2-ingest.yml` · `--profile trend-tick` |
| Ports | [`docs/docs/guides/service-ports.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/service-ports.md) |
| Degraded | [`docs/docs/guides/degraded-operations.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/degraded-operations.md) |
| Incidents | [`docs/docs/guides/incident-response.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/incident-response.md) |
| Calibration | [`docs/docs/guides/calibration-ops-runbook.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/calibration-ops-runbook.md) |
| AI / trend prod | [`docs/docs/guides/repo-productionization-runbook.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/repo-productionization-runbook.md) |
| Honesty | [`STUB_REGISTER.md`](https://github.com/pamu512/tarka/blob/master/STUB_REGISTER.md) |
| Common failures | [`docs/docs/operations/runbook-common-failures.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/operations/runbook-common-failures.md) |

CLI: `python tarka.py install --lite` / `start` / `status`. Trend: `make trend-tick` or `scripts/trend_tick_loop.sh`.
