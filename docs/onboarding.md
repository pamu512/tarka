# Onboarding

Day-1 path for engineers joining Tarka.

## Recommended (Docker)

Follow [`docs/docs/quickstart.md`](docs/quickstart.md): lite compose (evaluate + AGE), then `python3 scripts/oss/first_decision_smoke.py`. Desk home is Hunt (`/graph`). Leftovers are `/leftovers`. Observe is `/ops/shadow`.

## Docs map

| Need | Doc |
|------|-----|
| Hub | [`INDEX.md`](INDEX.md) |
| Architecture | [`docs/architecture.md`](docs/architecture.md) · root [`ARCHITECTURE.md`](../ARCHITECTURE.md) |
| Flows | [`docs/guides/feature-data-flows.md`](docs/guides/feature-data-flows.md) |
| Ports | [`docs/guides/service-ports.md`](docs/guides/service-ports.md) |

## Nix / Pulumi (optional)

If you use the flake: `nix develop` from repo root. Pulumi ADR: [`docs/docs/adr/0003-iac-via-pulumi.md`](docs/adr/0003-iac-via-pulumi.md). Prefer compose for fraud-desk work unless you are changing infra.
