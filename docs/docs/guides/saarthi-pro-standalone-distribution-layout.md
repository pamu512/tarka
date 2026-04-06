# Saarthi Pro — standalone distribution layout (reference)

> **Internal.** Describes the **expected** shape of the **private** [Saarthi-pro](https://github.com/pamu512/Saarthi-pro) repository or release bundle. Implement there; Tarka remains the **upstream reference** for agent source—**without** a Pro-named distribution directory in the OSS tree.

## Goals

- **Single artifact** (container image + Helm chart or Compose overlay) that ships the investigation copilot **without** pulling the full Tarka monorepo.
- **Pinned upstream:** `RELEASE.md` (or equivalent) lists fraud-stack **commit SHA** and **`contract_version`**.
- **Upgrade path:** [Upgrade from OSS](saarthi-pro-upgrade-from-oss.md).

## OSS agent image from Tarka (today)

Build **`services/investigation-agent/Dockerfile`** from the monorepo root for a **minimal investigation-agent** image (no `saarthi_pro` package). CI **`docker-build`** already builds this target for regression coverage.

**[Saarthi-pro](https://github.com/pamu512/Saarthi-pro)** (**private**) uses its own Dockerfile: **clones Tarka** and layers **`src/saarthi_pro/`** (Pro routes, license middleware, optional registry labels / `RELEASE.md`). Use that repo for **commercial** product images and SKU documentation.

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
