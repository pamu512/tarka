# Onboarding

Day-1 path for engineers joining Tarka.

## Recommended (Docker)

Follow [`docs/docs/quickstart.md`](docs/quickstart.md): lite + fraud-desk compose, then `python3 scripts/oss/first_decision_smoke.py`.

## Docs map

| Need | Doc |
|------|-----|
| Hub | [`INDEX.md`](INDEX.md) |
| Architecture | [`docs/architecture.md`](docs/architecture.md) · root [`ARCHITECTURE.md`](../ARCHITECTURE.md) |
| Flows | [`docs/guides/feature-data-flows.md`](docs/guides/feature-data-flows.md) |
| Honesty | root [`STUB_REGISTER.md`](../STUB_REGISTER.md) |
| Ports | [`docs/guides/service-ports.md`](docs/guides/service-ports.md) |

## Nix / Pulumi (optional)

If you use the flake: `nix develop` from repo root. Pulumi ADR: [`docs/docs/adr/0003-iac-via-pulumi.md`](docs/adr/0003-iac-via-pulumi.md). Prefer compose for fraud-desk work unless you are changing infra.
