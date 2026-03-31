# Rule Authoring Guide

Tarka uses JSON rule packs for fraud detection. Rules are evaluated on every decision request, and their outputs (tags, score deltas) are combined to produce a final fraud score. This guide covers the rule format, available operators, best practices, and how to test rules with backtesting.

---

## Rule Pack Format

Rules are organized into **packs** — JSON files stored in the `rules/` directory of the Decision API. Each pack contains two types of rules: **feature rules** (evaluated against event features) and **tag rules** (evaluated against existing entity tags).

```json
{
  "version": 1,
  "rules": [
    {
      "id": "high_amount_payment",
      "when": [
        { "op": "gte", "field": "amount", "value": 5000 }
      ],
      "tags": ["amount:high"],
      "score_delta": 15,
      "description": "Flag payments over $5,000"
    }
  ],
  "tag_rules": [
    {
      "id": "escalate_vpn_high_amount",
      "any_tag": ["amount:high", "sdk:vpn"],
      "tags": ["escalated:vpn_high_amount"],
      "score_delta": 20,
      "description": "Escalate when high amount + VPN"
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `version` | int | Always `1` (for forward compatibility) |
| `rules` | array | Feature-based rules |
| `tag_rules` | array | Tag-based rules |

---

## Feature Rules

Feature rules evaluate conditions against the event's feature dict (payload fields, device signals, and computed aggregates).

```json
{
  "id": "unique_rule_id",
  "when": [
    { "op": "gte", "field": "amount", "value": 10000 },
    { "op": "is_true", "field": "is_vpn" }
  ],
  "tags": ["amount:very_high", "compound:vpn_large_payment"],
  "score_delta": 25,
  "description": "Large payment from VPN"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Unique rule identifier (used in `rule_hits`) |
| `when` | array | Yes | Array of conditions — ALL must match (AND logic) |
| `tags` | string[] | No | Tags to apply when the rule fires |
| `score_delta` | float | No | Points to add to the base score (default 0) |
| `description` | string | No | Human-readable description |

### Condition Format

Each condition in the `when` array:

```json
{ "op": "gte", "field": "amount", "value": 5000 }
```

| Field | Type | Description |
|---|---|---|
| `op` | string | Operator to apply |
| `field` | string | Feature name to evaluate |
| `value` | any | Value to compare against |

---

## Available Operators

| Operator | Description | Example |
|---|---|---|
| `eq` | Exact equality | `{"op": "eq", "field": "country", "value": "NG"}` |
| `gte` | Greater than or equal | `{"op": "gte", "field": "amount", "value": 5000}` |
| `lte` | Less than or equal | `{"op": "lte", "field": "account_age_days", "value": 7}` |
| `in` | Value is in a list | `{"op": "in", "field": "country", "value": ["NG", "GH", "KE"]}` |
| `contains` | Substring match | `{"op": "contains", "field": "email", "value": "@tempmail"}` |
| `is_true` | Boolean true check | `{"op": "is_true", "field": "is_emulator"}` |
| `is_false` | Boolean false check | `{"op": "is_false", "field": "email_verified"}` |

!!! note "Multiple Conditions"
    All conditions in a rule's `when` array must match for the rule to fire (AND logic). To express OR logic, create separate rules with the same tags/score.

---

## Tag Rules

Tag rules fire based on tags that already exist on the entity (from Redis) or tags applied by other rules in the current evaluation. They use `any_tag` instead of `when` — if **any** of the listed tags are present, the rule fires.

```json
{
  "id": "escalate_velocity_vpn",
  "any_tag": ["velocity:high_1h", "sdk:vpn"],
  "tags": ["escalated:velocity_vpn"],
  "score_delta": 20,
  "description": "High velocity combined with VPN use"
}
```

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique rule identifier |
| `any_tag` | string[] | Fire if ANY of these tags exist on the entity |
| `tags` | string[] | Tags to apply |
| `score_delta` | float | Points to add |

---

## Velocity / Aggregate Features

The Decision API computes real-time aggregates from Redis and injects them into the feature dict before rule evaluation. These features are available in rule conditions:

### Count Aggregates

| Feature | Description |
|---|---|
| `event_count_1h` | Number of events in the last hour |
| `event_count_24h` | Number of events in the last 24 hours |
| `event_count_7d` | Number of events in the last 7 days |

### Sum / Average Aggregates

| Feature | Description |
|---|---|
| `sum_amount_1h` | Sum of `amount` in the last hour |
| `sum_amount_24h` | Sum of `amount` in the last 24 hours |
| `avg_amount_1h` | Average `amount` in the last hour |
| `avg_amount_24h` | Average `amount` in the last 24 hours |

### Distinct Count Aggregates

| Feature | Description |
|---|---|
| `distinct_ip_address_24h` | Distinct IP addresses in the last 24 hours |
| `distinct_device_id_24h` | Distinct device IDs in the last 24 hours |

### Device Signal Features

These are injected from `device_context.signals`:

| Feature | Description |
|---|---|
| `is_emulator` | Emulator/simulator detected |
| `is_vpn` | VPN detected |
| `is_bot` | Bot behavior detected |
| `is_repackaged` | App repackaging detected |
| `is_spoofed_location` | GPS spoofing detected |
| `webdriver_detected` | WebDriver automation detected |
| `headless_detected` | Headless browser detected |
| `automation_detected` | Automation framework detected |
| `timezone_geo_mismatch` | Timezone doesn't match geo |
| `ip_is_proxy` | IP identified as proxy |
| `ip_is_datacenter` | IP from known datacenter ASN |

---

## Real-World Rule Examples

### High-value payment from new account

```json
{
  "id": "new_account_high_payment",
  "when": [
    { "op": "gte", "field": "amount", "value": 2000 },
    { "op": "lte", "field": "account_age_days", "value": 7 }
  ],
  "tags": ["risk:new_account_high_payment"],
  "score_delta": 25,
  "description": "Payment over $2k from account less than 7 days old"
}
```

### Velocity spike

```json
{
  "id": "velocity_spike_1h",
  "when": [
    { "op": "gte", "field": "event_count_1h", "value": 20 }
  ],
  "tags": ["velocity:high_1h"],
  "score_delta": 25,
  "description": "More than 20 events in the last hour"
}
```

### High daily volume

```json
{
  "id": "high_daily_volume",
  "when": [
    { "op": "gte", "field": "sum_amount_24h", "value": 50000 }
  ],
  "tags": ["amount:high_daily_volume"],
  "score_delta": 20,
  "description": "Total amount exceeds $50k in 24h"
}
```

### Multiple devices

```json
{
  "id": "many_devices_24h",
  "when": [
    { "op": "gte", "field": "distinct_device_id_24h", "value": 3 }
  ],
  "tags": ["device:many_devices"],
  "score_delta": 20,
  "description": "Entity used more than 3 distinct devices in 24h"
}
```

### Emulator detection

```json
{
  "id": "sdk_emulator",
  "when": [{ "op": "is_true", "field": "is_emulator" }],
  "tags": ["sdk:emulator"],
  "score_delta": 30
}
```

### Compound escalation (tag rule)

```json
{
  "id": "escalate_velocity_vpn",
  "any_tag": ["velocity:high_1h", "sdk:vpn"],
  "tags": ["escalated:velocity_vpn"],
  "score_delta": 20,
  "description": "High velocity combined with VPN use"
}
```

---

## Rule Management API

Instead of editing JSON files directly, you can manage rules via the REST API.

### Create a Rule Pack

```bash
curl -X POST http://localhost:8000/v1/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Custom Payment Rules",
    "rules": [
      {
        "id": "custom_high_amount",
        "when": [{ "field": "amount", "op": "gte", "value": 10000 }],
        "tags": ["custom:high_amount"],
        "score_delta": 20,
        "description": "Flag amounts over 10k"
      }
    ],
    "tag_rules": []
  }'
```

### Add a Rule to an Existing Pack

```bash
curl -X POST http://localhost:8000/v1/rules/custom_payment_rules.json/rules \
  -H "Content-Type: application/json" \
  -d '{
    "id": "custom_night_payment",
    "when": [
      { "field": "hour_of_day", "op": "gte", "value": 22 },
      { "field": "amount", "op": "gte", "value": 1000 }
    ],
    "tags": ["custom:night_high_payment"],
    "score_delta": 15,
    "description": "Large payment during night hours"
  }'
```

### Delete a Rule

```bash
curl -X DELETE http://localhost:8000/v1/rules/custom_payment_rules.json/rules/custom_night_payment
```

---

## Rule Backtesting

Before deploying new rules to production, test them against historical events using the replay endpoint:

```bash
curl -X POST http://localhost:8000/v1/replay \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "rules_override": [
      {
        "id": "test_strict_amount",
        "when": [{ "field": "amount", "op": "gte", "value": 500 }],
        "tags": ["test:strict"],
        "score_delta": 40
      }
    ],
    "limit": 1000
  }'
```

The response shows a side-by-side comparison for each historical event:

- `original_decision` vs `new_decision`
- `original_score` vs `new_score`
- `decisions_changed` — total count of events where the decision would flip

Use this to tune `score_delta` values and thresholds before going live.

---

## Best Practices

1. **Use descriptive rule IDs.** Rule IDs appear in `rule_hits` and audit trails. Names like `velocity_high_1h` are more useful than `rule_17`.

2. **Keep score deltas moderate.** The base score is 10. Individual rules should typically add 5–30 points. Reserve 40+ for high-confidence signals like `is_bot` or `is_repackaged`.

3. **Use tag rules for compound signals.** Instead of complex multi-condition feature rules, let simple rules apply tags, then use tag rules to escalate when multiple signals combine.

4. **Version your rule packs.** Keep rule files in version control. The `version: 1` field is reserved for future schema changes.

5. **Test with replay before deploying.** Always backtest against real traffic to understand the impact of new rules on decision distribution.

6. **Separate concerns into packs.** Create separate pack files for velocity rules, device signal rules, amount rules, and geo rules. This makes it easier to toggle entire categories.

7. **Monitor rule_hits in audit data.** After deploying new rules, query the audit table to verify they're firing at expected rates.
