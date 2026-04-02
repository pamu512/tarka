# Module codenames (naming convention)

Tarka uses a **two-layer name** so scripts stay stable while product language stays memorable.

## Rules

1. **Slug (machine key)** — lowercase, no spaces: `core`, `graph`, `ml`. Used in `tarka.py`, Compose profiles, state files, and CI. **Do not rename** without a migration plan.
2. **Codename (human story)** — one word, Title Case, easy to say in demos and release notes. Chosen to echo **Nyāya**-style reasoning (like the word *Tarka* itself): proof, links, inference, records.
3. **Service directory names** — stay kebab-case (`decision-api`, `graph-service`); codenames are **not** folder names.
4. **SDK slugs** — keep `sdk-python`, `sdk-typescript`, … for package paths; codenames label them in the installer only.
5. **`Dwar` vs `Riti`** — **`Dwar`** is the operator **UI** (`frontend`). **`Riti`** is the **GraphQL gateway** (`gateway`): one aggregated API surface (metaphor: a **rusted** / hardened gate, not the Rust language unless you rewrite the service).

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
| `gateway` | **Riti** | रीति — convention, pattern; brand gloss **rust** (durable, weathered gate) for the GraphQL façade | GraphQL façade |
| `frontend` | **Dwar** | द्वार — door, portal | Operator UI |

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
