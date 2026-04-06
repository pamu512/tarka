# Unit21 Fraud DAO / Fraud Consortium vs Tarka `consortium_api` (pattern comparison)

**Disclaimer:** This note is **not** a partnership, certification, or recommendation of any vendor. **Unit21** is named only because their **public** materials describe a widely cited **shared fraud intelligence** model. Product names, APIs, hashing details, and membership rules **change over time**; verify against [Unit21’s current product pages](https://www.unit21.ai/products/fraud-consortium) and your counsel before any integration.

**Naming:** In Unit21’s marketing, **“Fraud DAO”** and **“Fraud Consortium”** refer to the **same network product** (they also use [fraud-dao.com](http://fraud-dao.com/) as a consumer-facing entry). This is **not** on-chain DAO governance in the smart-contract sense; it is **consortium-style** collaboration on **de-identified** fraud signals.

## Unit21 (public marketing pattern)

From Unit21’s blogs and product copy, the consortium emphasizes:

1. **Screening** — Check users **at onboarding** and **at payment initiation** against **shared** network intelligence.
2. **Ongoing monitoring** — Lifecycle monitoring of existing customers, not only first touch.
3. **Alerts** — **Real-time**, **rules-engine**-driven alerts with contextual logic inside the **Unit21 platform** (not described as a standalone OSS rules surface).
4. **Share / label** — **One-click** (or streamlined) contribution of **confirmed fraud**, with **standardized “Blocked Reasons”** (e.g. account takeover, scams, stolen identity categories in their examples) so the **network** updates.

They describe **privacy-preserving** sharing using **proprietary / patent-pending hashing** so **PII is not exposed** in the raw form members would recognize across firms. Scale and membership figures in their materials are **marketing claims**; treat operational SLAs and legal bases as **contract-specific**. They also describe folding the network into the **broader Unit21 platform** (screening, rules, cases); details evolve with their product roadmap.

### Public references (verify current)

- [Fraud Consortium product](https://www.unit21.ai/products/fraud-consortium)
- [fraud-dao.com](http://fraud-dao.com/) (marketing entry point; may redirect or mirror product messaging)
- [Fraud DAO expansion / features blog](https://www.unit21.ai/blog/unit21s-fraud-dao-expands-new-features-integration-and-growing-membership) (historical feature narrative; not a spec)

## Tarka `consortium_api` (decision-api)

Tarka implements a **self-hosted**, **Redis**-backed aggregate keyed by  
`hash_entity_id(consortium_secret, tenant_id, entity_id)` under `fraud:consortium:*`, gated by **`CONSORTIUM_ENABLED`**.

| Step | HTTP (prefix `/v1/consortium`) | Role |
|------|----------------------------------|------|
| **Share signal** | `POST /share` | `signal_type`, `severity`, reporter `tenant_id`; merges **multi-tenant** reports and **trust weights**. |
| **Lookup** | `GET /check/{tenant_id}/{entity_id}` | Read aggregate for that hash (**reporter tenant list stripped** from response). |
| **Feedback** | `POST /feedback` | `false_positive` \| `confirmed_fraud` — drives **false_positive_rate** and scoring penalty. |
| **Trust** | `POST /trust` | Per-tenant **trust_score** (0.1–2.0) for weighted contribution. |

**Evaluate path:** `POST /v1/evaluate` calls **`check_consortium_signal`** and applies **`consortium_score_delta()`** (minimum distinct reporters, caps, FP penalty). Implementation: `consortium_api.py`, `redis_store.py`, `consortium.py`, `main.py` under `services/decision-api/`.

Tarka does **not** ship a labeled **“Blocked Reasons”** taxonomy matching Unit21’s; you would map your own **reason codes** to **`signal_type`** strings and/or rules. There is **no** built-in Unit21 API client or **entity UID** graph from their network.

## Conceptual mapping

| Idea | Unit21 (as publicly described) | Tarka |
|------|---------------------------------|--------|
| **Screen / query** | Network lookup at onboarding or pay-in | `GET /v1/consortium/check/...` and/or implicit check on **`/v1/evaluate`** |
| **Shared badness signal** | De-identified consortium hit + platform rules | Aggregated **`signal_type`** counts + **`max_severity`** + trust-weighted quality |
| **Confirm / share back** | One-click fraud label → network update | `POST /v1/consortium/share` (new/stronger signal) and/or `POST /v1/consortium/feedback` |
| **Standardized labels** | “Blocked Reasons” categories | **Your** taxonomy → **`signal_type`** (string) conventions |
| **Rules + workflow** | Unit21 rules engine + case tooling | **Your** rules (YAML/OPA/etc.) + Case API / investigation flows |

## Integration sketch (adapter only)

For calling Tarka’s consortium endpoints directly (share / check / feedback / trust / batch ingest), use [`scripts/consortium_adapter/README.md`](../../../scripts/consortium_adapter/README.md).

If you use **both** a Unit21-backed network and Tarka:

1. **Inbound:** Map Unit21 **screening or alert payloads** (scores, flags, categories) into **`/v1/evaluate`** features/tags or a **thin service** that writes **`/v1/consortium/share`** with a **stable** `entity_id` and agreed **`signal_type`** vocabulary — **only** where contracts and privacy reviews allow.
2. **Outbound:** Map **confirmed fraud / false positive** outcomes from your ops queue into **`/v1/consortium/feedback`** (and optionally **`/share`**) so **local** consortium math matches **your** governance.

Do **not** assume **hash compatibility** between Unit21’s network and Tarka’s `consortium_secret` hash; a bridge almost always treats the vendor as **opaque** and maps to **your** entity key + **your** consortium lane (`CONSORTIUM_ID`).

## See also

- Same pattern class, different public operator: [`joinsonar-query-feedback-vs-consortium-api.md`](joinsonar-query-feedback-vs-consortium-api.md).
- Release context: [`releases/v1.2.0-2026-05-30.md`](../releases/v1.2.0-2026-05-30.md).
- Vendor-neutral framing: [`competitive-critical-review-2026-04.md`](competitive-critical-review-2026-04.md).
