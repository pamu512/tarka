# AI Pack-Author Contract

**Version:** 1  
**Audience:** BYO LLM backends (vLLM, Azure OpenAI-compat, Bedrock proxy, Vertex)  
**Enforced by:** `pack_author_contract.validate_ai_authored_pack()`

---

## Output specification

You must return **exactly one** JSON object representing a rule pack.
No markdown, no commentary, no wrapping. Raw JSON only.

### Required top-level fields

| Field | Type | Constraint |
|---|---|---|
| `name` | string | Non-empty, max 120 chars. Descriptive slug. |
| `version` | integer | Must be `1`. |
| `mode` | string | Must be `"shadow"`. No other mode is legal for AI-authored packs. |
| `is_ai_authored` | boolean | Must be `true`. |
| `authored_by` | string | Backend identifier (e.g. `"scout"`, `"vllm"`, `"azure"`, `"bedrock"`, `"vertex"`). Never a Tarka model brand. |
| `rules` | array | At least one rule. Max 50 rules. |

### Optional top-level fields

| Field | Type | Constraint |
|---|---|---|
| `description` | string | Max 500 chars. |
| `evidence` | object | Trace IDs, fingerprint values, counts, report_id references. |

---

## Rule structure

Each element of `rules` is an object:

| Field | Type | Constraint |
|---|---|---|
| `id` | string | Non-empty, max 80 chars. |
| `when` | array | 1–20 condition objects (see below). |
| `score_delta` | number | **5 ≤ score_delta ≤ 30**. No deny-100 / blacklist writes. |
| `description` | string | Optional, max 500 chars. |
| `tags` | array of string | Optional metadata tags. |
| `metadata` | object | Optional. Must include `"source"` naming the detection strategy. |

### Condition object (`when` element)

| Field | Type | Constraint |
|---|---|---|
| `field` | string | Must be a first-party evaluate field (see allowed list below). |
| `op` | string | One of the allowed operators (see below). |
| `value` | any | Comparison value appropriate for the operator. |

### Allowed `field` values (first-party evaluate fields only)

Event type and identity:
- `event_type` (values: `"login"`, `"payment"`, `"signup"`, `"device"`, `"session"`, `"custom"`)
- `entity_id`, `session_id`, `acc_id`, `user_id`

SDK device-context signals (already extracted):
- `device_fingerprint`, `canvas_hash`, `webgl_vendor`
- `user_agent`, `screen_resolution`, `timezone_offset`, `language`
- `platform`, `vendor`

Velocity / counter fields (already in packs):
- `tx_count_1h`, `tx_count_24h`, `tx_amount_1h`, `tx_amount_24h`
- `distinct_devices_24h`, `distinct_ips_24h`

Fingerprint / biometric signals:
- `vendor_fingerprint_score`, `vendor_incognia_risk`
- `ip_address`, `ip_risk_score`, `geo_country`, `geo_city`

Amount / payment:
- `amount`, `currency`

**Do not** use consortium fields, invented KYC fields, or graph-as-live-on-lite claims.

### Allowed operators

`eq`, `not_eq`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`,
`starts_with`, `ends_with`, `exists`, `not_exists`, `is_true`, `is_false`

**Do not** use `regex` (too broad for AI-authored rules).

---

## Hard stops

1. **Mode is always `shadow`** (Observe / canary). You cannot set `mode` to `"active"` or `"live"`.
2. **You cannot promote** a pack to live. Promotion is a human/gate operation.
3. **You cannot create a case.** Case creation is a separate service.
4. **You cannot call evaluate as the decider.** Evaluate stays Rust. You advise only.
5. **`score_delta` is bounded 5–30.** No deny-100, no blacklist writes.
6. **Silence is allowed.** If the evidence does not support a rule, return an empty `rules` array — but the validator requires at least one rule per pack, so only submit when you have evidence.
7. **Skipping a check is showing-signs, not a block.** Unless the host already has that pack deployed.

## Evidence requirement

The `evidence` field (or per-rule `metadata`) should cite concrete backing:
trace IDs, fingerprint values, account counts, report IDs.
Do not invent evidence. If you cannot cite evidence, do not emit a rule.

---

## Example valid pack

```json
{
  "name": "scout_canvas_burst_abc123",
  "version": 1,
  "mode": "shadow",
  "is_ai_authored": true,
  "authored_by": "scout",
  "description": "Coordinated canvas_hash burst detected by Scout",
  "evidence": {
    "report_id": "rpt-abc-123",
    "fingerprint_kind": "canvas_hash",
    "fingerprint_value": "a1b2c3d4e5f6",
    "distinct_account_count": 12
  },
  "rules": [
    {
      "id": "scout_canvas_hash_a1b2c3",
      "when": [
        {"field": "canvas_hash", "op": "eq", "value": "a1b2c3d4e5f6"}
      ],
      "score_delta": 25,
      "description": "Flag accounts sharing canvas hash from coordinated burst",
      "tags": ["scout:coordinated_burst"],
      "metadata": {
        "source": "scout_coordinated_burst"
      }
    }
  ]
}
```
