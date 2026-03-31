# Decision API

The Decision API is the central scoring engine. It receives fraud evaluation requests, orchestrates rules, ML models, and OPA policies in parallel, then returns a decision (`allow`, `review`, or `deny`) with a composite score.

**Port:** 8000
**Version:** 4.0.0
**Framework:** Python / FastAPI

---

## Endpoints

### Health Check

```
GET /v1/health
```

**Response:**

```json
{ "status": "ok" }
```

---

### Evaluate Decision

The primary endpoint. Accepts an event, runs the full scoring pipeline, and returns a fraud decision.

```
POST /v1/decisions/evaluate
```

**Request Body:**

```json
{
  "tenant_id": "acme",
  "event_type": "payment",
  "entity_id": "user-42",
  "session_id": "sess-abc123",
  "payload": {
    "amount": 499.99,
    "currency": "USD",
    "merchant": "electronics-store"
  },
  "device_context": {
    "device_id": "d-xxxx",
    "platform": "web",
    "signals": {
      "is_emulator": false,
      "is_vpn": true,
      "is_bot": false,
      "webdriver_detected": false,
      "headless_detected": false
    },
    "attestation": {
      "nonce": "abc123",
      "token": "signed-token",
      "provider": "browser_challenge"
    }
  },
  "metadata": {
    "ip": "203.0.113.42",
    "user_agent": "Mozilla/5.0..."
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `tenant_id` | string | Yes | Tenant identifier for multi-tenant isolation |
| `event_type` | string | Yes | One of: `login`, `payment`, `signup`, `device`, `session`, `custom` |
| `entity_id` | string | Yes | The user/account identifier being evaluated |
| `session_id` | string | No | Session identifier for session linking in the graph |
| `payload` | object | No | Event-specific data (amount, merchant, etc.) |
| `device_context` | object | No | Device signals from SDK (see below) |
| `metadata` | object | No | Additional context (IP, user agent, etc.) |

**Device Context:**

| Field | Type | Description |
|---|---|---|
| `device_id` | string | Unique device fingerprint |
| `platform` | string | `web`, `android`, `ios`, or `server` |
| `signals` | object | Device signal booleans (see SDK docs) |
| `attestation` | object | Platform attestation proof (optional) |

**Response:**

```json
{
  "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "decision": "review",
  "score": 55.0,
  "tags": ["sdk:vpn"],
  "rule_hits": ["sdk_vpn"],
  "reasons": ["rules:sdk_vpn", "signals:sdk:vpn"],
  "ml_score": null
}
```

| Field | Type | Description |
|---|---|---|
| `trace_id` | UUID | Unique identifier for this decision (use for audit lookups) |
| `decision` | string | `allow`, `review`, or `deny` |
| `score` | float | Composite score (0–100) |
| `tags` | string[] | All tags applied to this entity (cumulative) |
| `rule_hits` | string[] | IDs of rules that fired |
| `reasons` | string[] | Human-readable explanation strings |
| `ml_score` | float \| null | Raw ML model score if ML Scoring is configured |

---

### Attestation Challenge

Request a nonce for device attestation. The SDK signs this nonce using platform-specific attestation (Play Integrity, App Attest, or browser HMAC challenge) and sends the proof back via `attestation/verify`.

```
POST /v1/attestation/challenge
```

**Request:**

```json
{ "tenant_id": "acme" }
```

**Response:**

```json
{
  "nonce": "a3f8e2d1b4c5...",
  "expires_in": 300
}
```

---

### Attestation Verify

Verify a signed attestation token against the nonce.

```
POST /v1/attestation/verify
```

**Request:**

```json
{
  "nonce": "a3f8e2d1b4c5...",
  "token": "signed-attestation-token",
  "provider": "play_integrity"
}
```

| Provider | Description |
|---|---|
| `browser_challenge` | HMAC-based browser challenge |
| `play_integrity` | Google Play Integrity API |
| `app_attest` | Apple App Attest |

**Response:**

```json
{
  "valid": true,
  "device_integrity": "play_integrity"
}
```

---

### Get Audit Record

Retrieve the stored audit record for a decision by trace ID.

```
GET /v1/audit/{trace_id}
```

**Response:**

```json
{
  "trace_id": "a1b2c3d4-...",
  "tenant_id": "acme",
  "entity_id": "user-42",
  "event_type": "payment",
  "decision": "review",
  "score": 55.0,
  "tags": ["sdk:vpn"],
  "rule_hits": ["sdk_vpn"],
  "created_at": "2026-03-31T10:15:30"
}
```

---

### Reload Rules

Hot-reload all JSON rule packs from disk without restarting the service.

```
POST /v1/admin/rules/reload
```

**Response:**

```json
{ "ok": true }
```

---

### Rule CRUD API

Full CRUD for managing rule packs. See the [Rule Authoring Guide](../guides/rules.md) for the pack format.

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/rules` | List all rule packs |
| `GET` | `/v1/rules/{filename}` | Get a specific pack |
| `POST` | `/v1/rules` | Create a new pack |
| `PUT` | `/v1/rules/{filename}` | Update an existing pack |
| `DELETE` | `/v1/rules/{filename}` | Delete a pack |
| `POST` | `/v1/rules/{filename}/rules` | Add a rule to a pack |
| `DELETE` | `/v1/rules/{filename}/rules/{rule_id}` | Remove a rule from a pack |

---

### Replay / Backtesting

Re-evaluate historical events against modified rules to preview the impact of rule changes before deploying them.

```
POST /v1/replay
```

**Request:**

```json
{
  "tenant_id": "acme",
  "rules_override": [
    {
      "id": "test_high_amount",
      "when": [{ "field": "amount", "op": "gte", "value": 1000 }],
      "tags": ["amount:high"],
      "score_delta": 30,
      "description": "Flag amounts over 1000"
    }
  ],
  "limit": 500
}
```

**Response:**

```json
{
  "tenant_id": "acme",
  "events_evaluated": 247,
  "decisions_changed": 18,
  "results": [
    {
      "trace_id": "...",
      "entity_id": "user-42",
      "event_type": "payment",
      "original_decision": "allow",
      "original_score": 10.0,
      "original_rule_hits": [],
      "new_decision": "review",
      "new_score": 40.0,
      "new_rule_hits": ["test_high_amount"],
      "new_tags": ["amount:high"],
      "score_diff": 30.0,
      "decision_changed": true
    }
  ]
}
```

---

### WebSocket Live Feed

Stream real-time decisions to dashboards.

```
WebSocket /v1/decisions/ws
```

Messages are JSON objects matching the evaluate response format:

```json
{
  "trace_id": "...",
  "tenant_id": "acme",
  "entity_id": "user-42",
  "event_type": "payment",
  "decision": "allow",
  "score": 10.0,
  "tags": []
}
```

---

## Configuration

All settings are configured via environment variables or a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://fraud:fraud@localhost:5432/fraud` | Postgres connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `RULES_PATH` | `./rules` | Directory containing JSON rule packs |
| `API_KEYS` | _(empty)_ | Comma-separated API keys. Empty = no auth (dev mode) |
| `DENY_THRESHOLD` | `80` | Score at or above which the decision is `deny` |
| `REVIEW_THRESHOLD` | `50` | Score at or above which the decision is `review` |
| `SCORE_BLEND_STRATEGY` | `average` | How to combine rule and ML scores: `average`, `max`, or `rules_only` |
| `FEATURE_SERVICE_URL` | _(empty)_ | Feature Service URL. Empty = inline features from payload |
| `ML_SCORING_URL` | _(empty)_ | ML Scoring Service URL. Empty = skip ML scoring |
| `GRAPH_SERVICE_URL` | _(empty)_ | Graph Service URL. Empty = skip graph upserts |
| `OPA_URL` | _(empty)_ | OPA URL. Empty = skip OPA evaluation |
| `ATTESTATION_NONCE_TTL` | `300` | Nonce expiry in seconds |
| `ATTESTATION_HMAC_SECRET` | _(empty)_ | HMAC secret for browser attestation |
| `RATE_LIMIT_RPM` | `1000` | Rate limit in requests per minute |

---

## Score Blending

The final score is derived from two inputs: the **rule score** (base 10 + sum of `score_delta` from fired rules) and the **ML score** (0–100 from ML Scoring service).

| Strategy | Formula |
|---|---|
| `average` | `(rule_score + ml_score) / 2` |
| `max` | `max(rule_score, ml_score)` |
| `rules_only` | `rule_score` (ML score ignored) |

If ML Scoring is not configured or returns an error, the rule score is used as-is regardless of the strategy.

---

## Attestation Flow

```
1. Client SDK calls POST /v1/attestation/challenge → receives nonce
2. SDK signs nonce with platform-specific attestation:
   - Web: HMAC-SHA256(device_id, nonce + device_id)
   - Android: Google Play Integrity API
   - iOS: Apple App Attest
3. SDK includes { nonce, token, provider } in device_context.attestation
4. Decision API verifies the attestation during evaluation
5. Failed/missing attestation adds risk signal tags
```
