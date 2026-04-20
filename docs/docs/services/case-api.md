# Case API

The Case API provides investigation case management with workflow automation, SLA tracking, a full audit trail, WebSocket live feeds, and webhook delivery with a dead letter queue.

**Port:** 8002
**Version:** 4.0.0
**Framework:** Python / FastAPI

Canonical HTTP tables: **[API Reference — Case API](../api-reference.md#case-api)** · OpenAPI: `contracts/openapi/case-api.yaml`

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

### List Cases

```
GET /v1/cases?tenant_id=acme&status=open&limit=50
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tenant_id` | string | required | Tenant identifier |
| `status` | string | _(all)_ | Filter by status: `open`, `in_review`, `escalated`, `resolved`, `closed` |
| `limit` | int | 50 | Maximum cases to return |

**Response:**

```json
{
  "items": [
    {
      "id": "c1d2e3f4-...",
      "tenant_id": "acme",
      "title": "Suspicious payment from emulator",
      "entity_id": "user-42",
      "trace_id": "a1b2c3d4-...",
      "priority": "high",
      "status": "open",
      "labels": ["auto-escalated"],
      "assigned_team": null,
      "created_at": "2026-03-31T10:15:30",
      "updated_at": "2026-03-31T10:15:30"
    }
  ]
}
```

---

### Create Case

```
POST /v1/cases
```

**Request:**

```json
{
  "tenant_id": "acme",
  "title": "Suspicious payment from emulator",
  "entity_id": "user-42",
  "trace_id": "a1b2c3d4-...",
  "priority": "high"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `tenant_id` | string | Yes | Tenant identifier |
| `title` | string | Yes | Human-readable case title |
| `entity_id` | string | Yes | The entity under investigation |
| `trace_id` | string | No | Link to the decision that triggered this case |
| `priority` | string | No | `critical`, `high`, `medium`, or `low` |

Creating a case automatically:

1. Records an audit trail entry
2. Evaluates all workflows with the `case_created` trigger
3. Applies any workflow mutations (priority changes, team assignments, labels, comments)
4. Broadcasts the event to WebSocket subscribers

**Response:** The created case object (same shape as list items), status 201.

---

### Get Case

```
GET /v1/cases/{case_id}
```

**Response:** Single case object.

---

### Update Case

```
PATCH /v1/cases/{case_id}
```

**Request (partial update):**

```json
{
  "status": "in_review",
  "assigned_team": "fraud-ops",
  "priority": "critical"
}
```

Updatable fields: `status`, `priority`, `assigned_team`, `title`.

---

### Add Comment

```
POST /v1/cases/{case_id}/comments
```

**Request:**

```json
{
  "author": "analyst@company.com",
  "body": "Confirmed fraudulent — linked to known device ring."
}
```

**Response:**

```json
{ "ok": true }
```

---

### Apply Labels

Add labels to a case (merged with existing labels).

```
POST /v1/cases/{case_id}/labels
```

**Request:**

```json
{
  "labels": ["fraud-confirmed", "chargeback-filed"]
}
```

**Response:**

```json
{
  "ok": true,
  "labels": ["auto-escalated", "chargeback-filed", "fraud-confirmed"]
}
```

---

### Get Case Graph

Fetch the entity graph centered on the case's entity (proxied to Graph Service).

```
GET /v1/cases/{case_id}/graph?depth=2
```

**Response:** Same format as Graph Service `/v1/subgraph` — `{ nodes, edges }`.

---

### Get Case SLA

Check SLA status for a case.

```
GET /v1/cases/{case_id}/sla
```

**Response:**

```json
{
  "case_id": "c1d2e3f4-...",
  "priority": "high",
  "sla_deadline": "2026-03-31T14:15:30+00:00",
  "breached": false,
  "status": "open"
}
```

**SLA deadlines by priority:**

| Priority | SLA Window |
|---|---|
| `critical` | 1 hour |
| `high` | 4 hours |
| `medium` | 24 hours |
| `low` | 72 hours |

---

### Get Case Audit Trail

Full history of all mutations made to a case.

```
GET /v1/cases/{case_id}/audit?limit=50
```

**Response:**

```json
{
  "history": [
    {
      "actor": "analyst@company.com",
      "action": "update_case",
      "resource_type": "case",
      "resource_id": "c1d2e3f4-...",
      "changes": {
        "status": { "old": "open", "new": "in_review" }
      },
      "timestamp": "2026-03-31T11:00:00"
    },
    {
      "actor": "workflow-engine",
      "action": "workflow_mutation",
      "resource_type": "case",
      "resource_id": "c1d2e3f4-...",
      "changes": {
        "priority": { "old": "high", "new": "critical" },
        "status": { "old": "open", "new": "escalated" }
      },
      "timestamp": "2026-03-31T10:15:31"
    }
  ]
}
```

---

## Workflow Automation

Workflows are JSON files stored in the `workflows/` directory adjacent to the service. They define automated actions that fire when specific triggers occur.

### List Workflows

```
GET /v1/workflows
```

### Reload Workflows

Hot-reload workflow definitions from disk.

```
POST /v1/workflows/reload
```

### Trigger Workflow Manually

```
POST /v1/workflows/trigger
```

**Request:**

```json
{
  "trigger": "decision_deny",
  "case": { "id": "c1d2e3f4-...", "priority": "high", "labels": [] },
  "decision": { "score": 92, "tags": ["sdk:bot"] }
}
```

---

### Workflow Format

Each workflow JSON file has this structure:

```json
{
  "name": "Auto-escalate denied transactions",
  "enabled": true,
  "triggers": ["decision_deny"],
  "conditions": [
    { "field": "score", "op": "gte", "value": 90 }
  ],
  "actions": [
    { "type": "set_priority", "priority": "critical" },
    { "type": "escalate" },
    { "type": "add_label", "labels": ["auto-escalated", "high-risk"] },
    { "type": "add_comment", "message": "Auto-escalated: score >= 90 with deny decision" }
  ]
}
```

### Trigger Types

| Trigger | Fires When |
|---|---|
| `case_created` | A new case is created |
| `case_updated` | A case status changes |
| `decision_deny` | A fraud decision is `deny` |
| `decision_review` | A fraud decision is `review` |
| `sla_breach` | A case exceeds its SLA timer |

### Condition Operators

| Operator | Description |
|---|---|
| `eq` | Exact equality |
| `neq` | Not equal |
| `gte` | Greater than or equal |
| `lte` | Less than or equal |
| `in` | Value is in array |
| `contains` | Value is contained in string or array |
| `has_tag` | Case labels or decision tags contain the value |

### Action Types

| Action | Description | Parameters |
|---|---|---|
| `assign_team` | Route case to a team | `team: string` |
| `set_priority` | Override case priority | `priority: string` |
| `add_label` | Add labels to the case | `labels: string[]` |
| `escalate` | Set status to `escalated`, priority to `critical` | — |
| `add_comment` | Add an automated comment | `message: string` |
| `send_webhook` | Fire an HTTP POST to a URL | `url: string` |

### Example Workflows

**Route bot-flagged cases:**

```json
{
  "name": "Route bot-flagged cases to bot-review team",
  "enabled": true,
  "triggers": ["case_created"],
  "conditions": [
    { "field": "tags", "op": "contains", "value": "sdk:bot" }
  ],
  "actions": [
    { "type": "assign_team", "team": "bot-review" },
    { "type": "add_label", "labels": ["bot-flagged"] },
    { "type": "add_comment", "message": "Routed to bot-review team: sdk:bot tag detected" }
  ]
}
```

**Webhook on review decisions:**

```json
{
  "name": "Webhook notification on review decisions",
  "enabled": true,
  "triggers": ["decision_review", "decision_deny"],
  "conditions": [],
  "actions": [
    { "type": "send_webhook", "url": "https://hooks.example.com/fraud-alerts" }
  ]
}
```

---

## WebSocket Live Feed

Subscribe to real-time case events (creates, updates).

```
WebSocket /v1/cases/ws
```

**Messages:**

```json
{
  "event": "case_created",
  "case": {
    "id": "c1d2e3f4-...",
    "tenant_id": "acme",
    "title": "Suspicious payment",
    "status": "open",
    "priority": "high"
  }
}
```

---

## Webhook Dead Letter Queue

Failed webhook deliveries are stored in a DLQ for retry.

### View DLQ

```
GET /v1/webhooks/dlq
```

### Retry a Failed Webhook

```
POST /v1/webhooks/dlq/{webhook_id}/retry
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://fraud:fraud@localhost:5432/fraud_cases` | Postgres connection string |
| `GRAPH_SERVICE_URL` | _(empty)_ | Graph Service URL for case graph lookups |
| `CORS_ORIGINS` | _(empty)_ | Comma-separated CORS origins. Empty defaults to `http://localhost:3000` |
| `WORKFLOWS_PATH` | `./workflows` | Directory containing workflow JSON files |
| `RATE_LIMIT_RPM` | `600` | Rate limit in requests per minute |
