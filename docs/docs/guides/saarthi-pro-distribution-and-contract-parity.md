# Saarthi Pro — distribution & contract parity (internal)

> **Internal engineering + sales engineering reference.** Not a legal document. Aligns expectations across **Tarka** (OSS reference) and the **private** **[Saarthi-pro](https://github.com/pamu512/Saarthi-pro)** commercial repository.

## Repositories and images

| Repository / artifact | Role |
|----------------------|------|
| **Tarka** (`pamu512/tarka`) | Canonical **open** `services/investigation-agent` + `services/shared`, integration contract, golden CI, `services/investigation-agent/Dockerfile` (built in CI **`docker-build`** matrix), maintainer docs. **No** Pro-branded distribution subtree or Pro-only CI jobs. |
| **[Saarthi-pro](https://github.com/pamu512/Saarthi-pro)** (**private**) | **Commercial** repo: **`saarthi_pro.asgi`**, **`/v1/pro`**, edition + **optional license-key** middleware, **Dockerfile** `git clone`s Tarka (`TARKA_GIT_REF`), registry images, `RELEASE.md`, vendor build scripts. |

**Integration contract** means the **behavior and JSON shape** described by `INTEGRATION_CONTRACT_VERSION`, [investigation-agent-integration-contract.md](investigation-agent-integration-contract.md), and [CHANGELOG_INTEGRATION.md](CHANGELOG_INTEGRATION.md)—including tool names, snapshot fields, and upstream-suppression rules.

## Default parity rule

For any **Saarthi Pro** release tag:

1. The shipped investigation agent (or embedded equivalent) MUST report a **`contract_version`** that exists in [CHANGELOG_INTEGRATION.md](CHANGELOG_INTEGRATION.md) for that lineage.
2. Pro SHOULD be built from a **specific fraud-stack commit** (or a fork that only adds packaging) and that mapping SHOULD be recorded in Pro’s release notes.
3. If Pro **lags** OSS, the lag is **explicit**: e.g. “Pro 0.4.0 = contract 1.1.0; OSS main is 1.2.0—upgrade path in release notes.”

## When parity may intentionally diverge (narrow)

- **Security or compliance hotfix** in Pro only: allowed for a **bounded** period if documented; merge back to OSS or bump contract with changelog as soon as practical.
- **Packaging-only** differences (env defaults, bundled deps) MUST NOT change **`contract_version`** semantics without a changelog entry.

## OSS agent image from this repo

From the monorepo root: `docker build -f services/investigation-agent/Dockerfile -t investigation-agent:local .` — same artifact CI validates under **`docker-build`** (`investigation-agent`). Versioned **commercial** images and release records live in **Saarthi-pro** only.

## Customer-facing one-pager (draft bullets)

Use in RFPs and security questionnaires:

- “Saarthi Pro ships a **versioned integration contract** (`contract_version` on `GET /v1/integration`).”
- “Contract changes are listed in our **integration changelog**; major bumps include migration notes.”
- “Commercial releases **pin** a contract version; optional **adapter certification** uses the same golden profiles as our reference CI.”

## Related

- [Saarthi Pro roadmap](saarthi-pro-roadmap.md) (Phase 1–3 [artifact index](saarthi-pro-roadmap.md#phase-13-artifact-index-quick-links))
- [Upgrade from OSS](saarthi-pro-upgrade-from-oss.md)
- [Adapter catalog & certification](saarthi-pro-adapter-catalog-and-certification.md)
- [Saarthi customer API change policy](saarthi-customer-api-change-policy.md)
