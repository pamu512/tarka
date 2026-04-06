# Join Sonar query/feedback vs Tarka `consortium_api` (pattern comparison)

**Disclaimer:** This note is **not** a partnership, certification, or recommendation of any vendor. **Join Sonar** is named only as a **publicly documented example** of a consortium-style **query → enrich → feedback** flow. Product names, APIs, and legal framing **change over time**; verify against the operator’s current documentation and your counsel before any integration.

## Join Sonar (public marketing pattern)

From [joinsonar.com](https://joinsonar.com/) and their docs site, the consortium describes a **three-step** loop:

1. **Send request** — Member sends **identifying attributes** (e.g. contact or transaction fields) via **API** to resolve or match an **entity** in the network.
2. **Receive response** — Member receives **risk-oriented enrichment** (scores, reputation, signals, or routed partner data) to fold into local decisioning.
3. **Send feedback** — After a decision, member **posts feedback** so the shared model/network can update ([API docs area](https://docs.joinsonar.com/api-reference/post-feedbacks)).

Operational details (auth, payloads, data packs, 314(b)/GLBA/FCRA claims) are **vendor-specific** and outside this repo.

## Tarka `consortium_api` (decision-api)

Tarka keeps consortium state in **Redis** under `fraud:consortium:*`, gated by **`CONSORTIUM_ENABLED`**. The **entity key** is a **deterministic hash** — `hash_entity_id(consortium_secret, tenant_id, entity_id)` — so **raw identifiers are not required** in HTTP paths for check/share (they are still used **inside your deployment** to compute the hash). Implementation: `services/decision-api/src/decision_api/consortium_api.py`, `redis_store.py`, `consortium.py`.

| Step | HTTP (prefix `/v1/consortium`) | Role |
|------|----------------------------------|------|
| **Publish / share signal** | `POST /share` | Body: `tenant_id`, `entity_id`, `signal_type`, `severity`, optional `ttl_days`, optional `consortium_id`. Records **reporter tenants**, **signal counts**, **severity**, **trust-weighted** aggregates. |
| **Lookup (“query”)** | `GET /check/{tenant_id}/{entity_id}` | Returns whether consortium is enabled and the **aggregated signal** for that hash (tenant IDs are **omitted** from the returned payload for privacy). |
| **Feedback** | `POST /feedback` | Body: `tenant_id`, `entity_id`, `outcome` ∈ `false_positive` \| `confirmed_fraud`, optional `ttl_days`. Updates **false-positive / confirmed-fraud counts** and derived **false_positive_rate** used in scoring quality. |
| **Trust (extra)** | `POST /trust` | Body: `tenant_id`, `trust_score` (0.1–2.0). Weights how much each reporter contributes to the aggregate. |

During **`POST /v1/evaluate`**, if consortium is enabled, the API **checks** the same hash and applies **`consortium_score_delta()`** so shared signals can **raise the risk score** (with **`CONSORTIUM_MIN_TENANTS`**, caps, and false-positive penalty). See `services/decision-api/src/decision_api/main.py`.

## Conceptual mapping

| Idea | Join Sonar (as publicly described) | Tarka |
|------|--------------------------------------|--------|
| **Query** | Outbound API call with attributes → network response | `GET /v1/consortium/check/...` **or** implicit check on **evaluate** |
| **Signal in** | Network returns enrichment | `POST /v1/consortium/share` records **your** tenants’ contributions to the **shared Redis record** for that entity hash |
| **Feedback** | Post-decision feedback to the network | `POST /v1/consortium/feedback` adjusts **FP / confirmed** counters on that hash’s record |
| **Trust / quality** | (Vendor-specific) | `POST /v1/consortium/trust` per reporting tenant |

Tarka does **not** implement a third-party consortium wire protocol, **entity UID** catalog, or **revenue share**; it implements a **self-hosted, opt-in** aggregate suitable for **multiple tenants** sharing one Redis-backed “lane” (`CONSORTIUM_ID`) with a **shared secret** for hashing.

## Integration sketch (adapter only)

Ready-to-use **HTTP client + CLI + JSON Lines ingest** for this API: [`scripts/consortium_adapter/README.md`](../../../scripts/consortium_adapter/README.md) (repo root).

A **bridge** between an external consortium and Tarka is usually:

1. On **inbound** risk events: map the vendor’s response (or your internal entity key) to **`POST /v1/evaluate`** payload fields and/or call **`GET /v1/consortium/check/...`** if you also mirror signals locally.
2. On **confirmed outcomes**: map vendor feedback APIs to **`POST /v1/consortium/share`** and/or **`POST /v1/consortium/feedback`** so **local** consortium scoring stays consistent with **your** governance — **only** if legal and contractual rules allow that mapping.

**Tenant isolation:** Consortium features must remain **consistent with your** deployment boundaries; do not merge another network’s PII into Tarka without explicit design and policy review.

## See also

- Related public pattern (Unit21 **Fraud DAO** / Fraud Consortium): [`unit21-fraud-dao-vs-consortium-api.md`](unit21-fraud-dao-vs-consortium-api.md).
- Release context: [`releases/v1.2.0-2026-05-30.md`](../releases/v1.2.0-2026-05-30.md) (DAO / consortium scope).
- Competitive framing (vendor-neutral): [`competitive-critical-review-2026-04.md`](competitive-critical-review-2026-04.md).
