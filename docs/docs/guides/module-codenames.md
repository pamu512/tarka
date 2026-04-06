# Module codenames (naming convention)

Tarka uses a **two-layer name** so scripts stay stable while product language stays memorable.

## Rules

1. **Slug (machine key)** — lowercase, no spaces: `core`, `graph`, `ml`. Used in `tarka.py`, Compose profiles, state files, and CI. **Do not rename** without a migration plan.
2. **Codename (human story)** — one word, Title Case, easy to say in demos and release notes. Chosen to echo **Nyāya**-style reasoning (like the word *Tarka* itself): proof, links, inference, records.
3. **Service directory names** — stay kebab-case (`decision-api`, `graph-service`); codenames are **not** folder names.
4. **SDK slugs** — keep `sdk-python`, `sdk-typescript`, … for package paths; codenames label them in the installer only.
5. **`Dwar` vs `Riti`** — **`Dwar`** is the operator **UI** (`frontend`). **`Riti`** is the **GraphQL gateway** (`gateway`). See [Etymology: Riti](#etymology-riti-gateway) for the technical Sanskrit sense (iron rust, Vajralepa).

## Stack modules

| Slug | Codename | Meaning / vibe | Role |
|------|----------|----------------|------|
| `core` | **Hetu** | हेतु — ground, reason, “because” | Real-time decisioning, rules, OPA, Redis |
| `graph` | **Jaala** | जाल — net | Entity graph, rings, link risk |
| `cases` | **Lekh** | लेख — writing, record | Cases, workflow, SAR/labeling |
| `integration` | **Setu** | सेतु — bridge | Ingress, adapters, OSINT |
| `ml` | **Anumana** | अनुमान — inference | ML scoring, features, drift |
| `agent` | **Saarthi** | सारथि — charioteer, one who steers | Investigation copilot |
| `streaming` | **Srotas** | स्रोतस् — current, stream | NATS / event ingest |
| `analytics` | **Kala** | काल — time | ClickHouse / historical analytics |
| `gateway` | **Riti** | रीति — iron rust (technical lexicon); *Vajralepa* ingredient → binding join layer | GraphQL façade |
| `frontend` | **Dwar** | द्वार — door, portal | Operator UI |

**Saarthi (`agent`):** open reference at `services/investigation-agent`; **container:** `services/investigation-agent/Dockerfile`. **[Saarthi-pro](https://github.com/pamu512/Saarthi-pro)** is the **private commercial** repo (wraps the same agent via `saarthi_pro.asgi`, **`/v1/pro`**, optional license gate; clones Tarka at build time). Comparison: [Saarthi Pro vs OSS](saarthi-pro-vs-oss.md). Roadmap / parity: [Saarthi Pro roadmap](saarthi-pro-roadmap.md), [distribution & contract parity](saarthi-pro-distribution-and-contract-parity.md).

### Etymology: Riti (`gateway`)

**Rīti** (रीति) is attested in ancient Sanskrit technical discourse. In texts such as the *Viṣṇudharmottarapurāṇa*, **rīti** is interpreted as the **rust of iron** and was used as a material component in the preparation of **Vajralepa**—a specialized, very **hard cement**.

Tarka uses **Riti** as the codename for the **GraphQL gateway** because that service acts as a **cementing layer**: it aggregates many REST backends into one coherent, durable API surface—joining services the way Vajralepa binds its constituents into a single hardened mass. This is **not** a reference to the Rust programming language unless the gateway implementation is later rewritten in Rust.

## SDK modules

| Slug | Codename | Note |
|------|----------|------|
| `sdk-python` | **Duta** | दूत — messenger; server-side envoy |
| `sdk-typescript` | **Darpana** | दर्पण — mirror; browser surface |
| `sdk-android` | **Kavacha** | कवच — armor; device integrity |
| `sdk-ios` | **Mudra** | मुद्रा — seal; App Attest / stamp |

## How to use in copy

- **Marketing:** “Ship **Hetu** + **Jaala** first, add **Anumana** when you are ready for models.”
- **Engineering:** `python tarka.py install --modules core,graph,ml` (slugs unchanged).
- **Release notes:** Prefer codename + slug once: “**Hetu** (`core`): inference contract …”.

## Changing codenames

Codenames are **product labels**. If you rename one, update:

- `tarka.py` (`MODULES` / `SDK_MODULES` `codename` fields)
- This document
- Any announcement or wiki that quoted the old codename

Do **not** change slugs lightly.
