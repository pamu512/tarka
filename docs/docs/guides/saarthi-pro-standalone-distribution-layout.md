# Saarthi Pro — standalone distribution layout (reference)

> **Internal.** Describes the **expected** shape of the [Saarthi-pro](https://github.com/pamu512/Saarthi-pro) repository or release bundle. Implement in Pro; fraud-stack remains the **upstream reference** for the agent source.

## Goals

- **Single artifact** (container image + Helm chart or Compose overlay) that ships the investigation copilot **without** pulling the full Tarka monorepo.
- **Pinned upstream:** `RELEASE.md` (or equivalent) lists fraud-stack **commit SHA** and **`contract_version`**.
- **Upgrade path:** [Upgrade from OSS](saarthi-pro-upgrade-from-oss.md).

## Shippable image in fraud-stack (today)

The monorepo includes a **first-party** build in **[`distributions/saarthi-pro-agent/`](../../../distributions/saarthi-pro-agent/README.md)** (`Dockerfile`, `RELEASE.md`, example Compose, `scripts/build_saarthi_pro_agent_image.*`). Build context remains the **repo root**; OCI labels record Pro version, git SHA, and contract version. Mirror or submodule this tree into [Saarthi-pro](https://github.com/pamu512/Saarthi-pro) for a standalone git remote if desired.

## Suggested repository layout (Saarthi-pro)

```text
Saarthi-pro/
  README.md                 # Support contacts, license, link to public contract doc
  RELEASE.md                # Version line: Pro x.y.z ↔ fraud-stack SHA ↔ contract_version
  docker/
    Dockerfile              # FROM scratch or slim; COPY investigation-agent from submodule or vendored tree
  helm/saarthi-pro-agent/   # Optional: values.yaml, probes, secrets refs
  docs/
    INSTALL.md              # Customer-facing install (or link to private portal)
  vendor/                   # Optional: git submodule → fraud-stack at pinned commit
```

## Build options (pick one)

1. **Submodule:** `vendor/fraud-stack` at tagged commit; Docker `COPY` only `services/investigation-agent` + `services/shared` if needed.
2. **Vendored snapshot:** Script copies subtree at release time; smaller clone for air-gapped builds.
3. **Fork:** Long-lived fork with Pro-only branches—document merge policy from upstream to avoid contract drift.

## Release artifact contents

- Image digest or tarball checksum
- **SBOM** (target: Phase 2 procurement)
- Link to [CHANGELOG_INTEGRATION](CHANGELOG_INTEGRATION.md) for contract line
- Diff of **default env** vs OSS defaults (if any)

## Related

- [Saarthi Pro roadmap](saarthi-pro-roadmap.md)
- [Distribution & contract parity](saarthi-pro-distribution-and-contract-parity.md)
