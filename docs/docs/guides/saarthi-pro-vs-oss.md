# Saarthi Pro vs open source (OSS)

> **Publication hold:** Do **not** publish this page on a public docs site, changelog, or marketing channel until **Saarthi Pro commercial packaging is approved** and the **SKU you sell** matches what is documented (see [Saarthi Pro roadmap](saarthi-pro-roadmap.md)). Until then, treat as **internal / maintainer** reference.

**Saarthi** is the product codename for the Investigation Copilot (LLM tool-use loop against case, graph, and decision APIs). **Tarka** (`github.com/pamu512/tarka`) ships the open reference as **`services/investigation-agent`**—the **implementation source of truth** for tool behavior and **`GET /v1/integration`**.

**Commercial packaging** lives only in the **private [Saarthi-pro](https://github.com/pamu512/Saarthi-pro)** repository (access by invitation): **Pro extension layer** in Python (`saarthi_pro.asgi`) mounts the upstream FastAPI app, adds **`/v1/pro/*`** routes, edition middleware, optional **`X-License-Key`** gate, **Dockerfile** that clones Tarka (`TARKA_GIT_REF`), registry images, release notes, and vendor-only build scripts. Tarka does **not** ship a separate Pro-branded distribution tree or CI job for that product.

**OSS agent container:** build from **`services/investigation-agent/Dockerfile`** at the monorepo root (same target as CI job **`docker-build`** matrix entry `investigation-agent`). Use that for minimal air-gapped or self-built images; **Pro-style** labeling, `RELEASE.md`, and commercial SKUs are documented in Saarthi-pro only.

Vendor **support, SLAs, DPAs, and maintained adapters** attach to **Saarthi Pro** SKUs; releases **pin** a Tarka commit and **`contract_version`** (see [distribution & contract parity](saarthi-pro-distribution-and-contract-parity.md)).

## Quick comparison

| Dimension | OSS in Tarka / fraud-stack (`investigation-agent`) | Saarthi Pro (commercial) |
|-----------|---------------------------------------------------|-------------------------|
| **Source & stack** | Full modular platform via `tarka.py` + Compose **or** `docker build -f services/investigation-agent/Dockerfile` from repo root | **Private [Saarthi-pro](https://github.com/pamu512/Saarthi-pro)** product image (clones Tarka + Pro layer); release notes pin **Tarka ref** + **`contract_version`** |
| **Operations** | You run upgrades, uptime, capacity, incident response | **Vendor:** managed options, SLAs, named support channel, runbooks (where sold) |
| **Enterprise identity** | API keys; **gateway pattern** for SSO (see [SSO/SCIM guide](saarthi-pro-sso-scim-integration-guide.md)) | **Vendor-assisted** IdP integration playbooks, SCIM/user-lifecycle documentation per deal |
| **Compliance narrative** | You map controls to your SOC2/ISO program; templates in-repo ([DPA outline](saarthi-pro-dpa-subprocessor-template.md), [VPC/residency](saarthi-pro-residency-vpc-deployment.md)) | **Signed** DPA, live subprocessor list, attestation language on **order form** |
| **Governance** | Maker–checker for sensitive tools, strict assurance mode, regional AI governance profiles, audit-oriented **`evidence_bundle_draft`** (v0/v1/dual) + structured logs | **Curated** prompt/skill libraries, policy templates as **reviewed SKUs**, contractual governance commitments |
| **Integrations** | **Versioned integration contract** (`GET /v1/integration`), golden CI profiles, OSS cookiecutter [`templates/cookiecutter-investigation-integration-adapter/`](../../../templates/cookiecutter-investigation-integration-adapter/), [named `INTEGRATION_PROFILE_ID`s](saarthi-pro-adapter-catalog-and-certification.md); **you** maintain adapters unless on a Pro tier | **Maintained adapter** (engineering + certification per SOW), implementation support, faster time-to-signed conformance |
| **Models & cost** | BYOK; you own spend and limits | Optional **bundled inference** SKUs, clearer seat/MAU economics (see [economics appendix](saarthi-pro-economics-packaging-appendix.md)) |
| **Trust & liability** | Community + **your** legal review; **evidence_bundle v1** adds provenance hashes—not proof that prose is true | **Commercial terms**, support credits, **optional** indemnity add-ons (counsel-reviewed)—same technical limits on LLM factual guarantees |
| **Depth & observability** | **Optional** org analytics hooks (`COPILOT_ANALYTICS_*`: turn + feedback events to log or webhook); tool-quality structured logs; feedback/review SQLite | **Productized** multi-tenant admin and **hosted** analytics (roadmap); vendor-operated telemetry pipelines where offered |
| **LLM trust & data boundary** | **Reference hardening:** injection sanitize/reject, heuristic **claims** grounding (not full prose verification), truncation, `COPILOT_*` toggles, BYOK. **Evidence v1** improves **audit export shape**, not model correctness. **You** own DPIA and LLM subprocessors for BYOK. | **Contractual** packaging: DPAs where offered, residency narrative, **governance product** depth—not a different “magic” model, **operational + legal** wrap around the **same** tool-first design. |

## Who should choose which

- **OSS** fits platform teams that already run Tarka (or a fork), are comfortable self-hosting the agent service, and want maximum control with no vendor dependency for the copilot binary.
- **Saarthi Pro** fits organizations that want the **same copilot design** (human-in-the-loop, explicit tools, systems of record) but need **procurement-grade** packaging: contracts, support, and productized governance—not a DIY integration project.

## Relationship to the architecture

Both align with the same principle: the model **proposes**, services of record **answer**, and humans **remain accountable** for outcomes that matter to regulators and litigation. Neither positions the copilot as an autonomous case closer.

**Links:** [Tarka (OSS)](https://github.com/pamu512/tarka) · [Saarthi-pro (private commercial repo)](https://github.com/pamu512/Saarthi-pro) · [Module codenames — Saarthi](module-codenames.md)

**Internal**

- [Saarthi Pro roadmap](saarthi-pro-roadmap.md) (Phases 0–3: playbooks + **OSS agent features** shipped in fraud-stack; **commercial** execution = registry publish, signed terms, maintained adapters per customer)
- [Adapter-first strategy & illustrative pricing](saarthi-pro-adapter-strategy-and-pricing.md) — **internal** until finance/legal approve customer-facing pricing sheets
- [Distribution & contract parity](saarthi-pro-distribution-and-contract-parity.md) (fraud-stack vs Saarthi-pro)
- [Adapter catalog & certification](saarthi-pro-adapter-catalog-and-certification.md) (golden profiles + named SKUs)
- [Assurance, warranties & liability (positioning)](saarthi-pro-assurance-liability-positioning.md) — RFP / demo guardrails
- Agent image build: `services/investigation-agent/Dockerfile` (repo root context); commercial release record → Saarthi-pro
