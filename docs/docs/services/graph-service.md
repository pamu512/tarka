# Graph Service

The Graph Service manages an entity graph backed by Neo4j. It handles entity resolution, relationship linking, tag storage on nodes, and provides graph analytics endpoints for community detection, fraud ring identification, risk propagation, and shared attribute analysis — all using pure Cypher queries (no GDS plugin required).

**Port:** 8001
**Version:** 3.0.0
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

### Upsert Entity

Create or update an entity node in the graph. If the entity already exists (matched by `tenant_id` + `external_id`), its properties and tags are merged.

```
POST /v1/entities
```

**Request:**

```json
{
  "tenant_id": "acme",
  "entity_type": "Account",
  "external_id": "user-42",
  "properties": {
    "last_event": "payment",
    "email": "user@example.com"
  },
  "tags": ["sdk:vpn", "velocity:high_1h"]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `tenant_id` | string | Yes | Tenant identifier |
| `entity_type` | string | Yes | Node label. Built-in: `Person`, `Account`, `Device`, `Payment`, `Document`, `Custom`. Custom types can be added via schema configuration. |
| `external_id` | string | Yes | Your system's identifier for this entity |
| `properties` | object | No | Arbitrary key-value properties stored on the node |
| `tags` | string[] | No | Tags applied to the node (cumulative) |

**Response:**

```json
{
  "graph_id": "4:abc123:0",
  "entity_type": "Account",
  "external_id": "user-42"
}
```

---

### Update Entity Tags

Merge additional tags onto an existing entity.

```
POST /v1/entities/{external_id}/tags
```

**Request:**

```json
{
  "tenant_id": "acme",
  "tags": ["fraud", "chargedback"]
}
```

**Response:**

```json
{
  "tags": ["fraud", "chargedback", "sdk:vpn"]
}
```

---

### Get Entity Tags

```
GET /v1/entities/{external_id}/tags?tenant_id=acme
```

**Response:**

```json
{
  "tags": ["sdk:vpn", "fraud"]
}
```

---

### Create Link

Create a relationship between two entities. Both entities must exist.

```
POST /v1/links
```

**Request:**

```json
{
  "tenant_id": "acme",
  "from_external_id": "user-42",
  "to_external_id": "device-abc",
  "relationship": "USED",
  "properties": {
    "trace_id": "a1b2c3d4...",
    "event_type": "payment"
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `tenant_id` | string | Yes | Tenant identifier |
| `from_external_id` | string | Yes | Source entity external ID |
| `to_external_id` | string | Yes | Target entity external ID |
| `relationship` | string | Yes | Relationship type. Built-in: `USED`, `SHARED_WITH`, `REFERRED`, `KYC_VERIFIED_BY`, `OWNS`, `CUSTOM`, `RELATED` |
| `properties` | object | No | Properties stored on the relationship edge |

**Response:**

```json
{ "ok": true }
```

---

### Query Subgraph

Retrieve the neighborhood around an entity up to a configurable depth (1–5 hops).

```
GET /v1/subgraph?entity_id=user-42&tenant_id=acme&depth=2
```

**Response:**

```json
{
  "nodes": [
    {
      "id": "user-42",
      "labels": ["Account"],
      "properties": {
        "tenant_id": "acme",
        "external_id": "user-42",
        "tags": ["sdk:vpn"]
      }
    },
    {
      "id": "device-abc",
      "labels": ["Device"],
      "properties": {
        "tenant_id": "acme",
        "external_id": "device-abc",
        "platform": "web"
      }
    }
  ],
  "edges": [
    {
      "from_id": "user-42",
      "to_id": "device-abc",
      "type": "USED",
      "properties": { "event_type": "payment" }
    }
  ]
}
```

---

## Schema Configuration

Each tenant can define custom entity types and relationship types beyond the built-in defaults.

### Get Schema

```
GET /v1/schema/{tenant_id}
```

**Response:**

```json
{
  "tenant_id": "acme",
  "entity_types": ["Person", "Account", "Device", "Payment", "Document", "Custom", "Merchant"],
  "relationship_types": ["USED", "SHARED_WITH", "REFERRED", "KYC_VERIFIED_BY", "OWNS", "CUSTOM", "RELATED", "PURCHASED_FROM"],
  "extra": {}
}
```

### Update Schema

```
PUT /v1/schema/{tenant_id}
```

**Request:**

```json
{
  "entity_types": ["Merchant", "Card"],
  "relationship_types": ["PURCHASED_FROM", "CHARGED_TO"],
  "extra": { "description": "E-commerce schema extensions" }
}
```

Custom types are merged with built-in defaults. Type names must match `^[A-Za-z][A-Za-z0-9_]{0,63}$` to prevent Cypher injection.

---

## Analytics Endpoints

### Community Detection

Find connected components (clusters of related entities) for a tenant.

```
GET /v1/analytics/communities?tenant_id=acme&min_size=3
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tenant_id` | string | required | Tenant to analyze |
| `min_size` | int | 3 | Minimum number of members to qualify as a community |

**Response:**

```json
[
  {
    "community_id": 0,
    "member_count": 7,
    "member_ids": ["user-1", "user-2", "device-a", "device-b", "card-x", "ip-1", "session-z"],
    "member_labels": ["Account", "Device", "Custom"],
    "shared_attributes": ["sdk:vpn", "velocity:high_1h"]
  }
]
```

---

### Risk Propagation

Starting from a known-risky entity, propagate risk scores outward through the graph with exponential decay per hop.

```
GET /v1/analytics/risk-propagation?tenant_id=acme&entity_id=user-42&depth=3&decay=0.5
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tenant_id` | string | required | Tenant identifier |
| `entity_id` | string | required | The risky entity to propagate from |
| `depth` | int | 3 | Maximum hops to traverse (clamped 1–5) |
| `decay` | float | 0.5 | Multiplier per hop. At depth 1 → `100 * 0.5 = 50`, depth 2 → `25`, etc. |

**Response:**

```json
[
  {
    "entity_id": "device-abc",
    "entity_labels": ["Device"],
    "propagated_risk_score": 50.0,
    "distance": 1,
    "path_description": "(user-42) -[USED]-> (device-abc)"
  },
  {
    "entity_id": "user-99",
    "entity_labels": ["Account"],
    "propagated_risk_score": 25.0,
    "distance": 2,
    "path_description": "(user-42) -[USED]-> (device-abc) -[USED]-> (user-99)"
  }
]
```

---

### Shared Attributes

Find entities that share a common property value, such as the same device ID, IP address, or card hash.

```
GET /v1/analytics/shared-attributes?tenant_id=acme&attribute=device_id&min_shared=2
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tenant_id` | string | required | Tenant identifier |
| `attribute` | string | `device_id` | Property name to check for sharing |
| `min_shared` | int | 2 | Minimum number of entities sharing the value |

**Response:**

```json
[
  {
    "attribute": "device_id",
    "shared_value": "device-abc",
    "entity_ids": ["user-42", "user-99", "user-101"],
    "group_size": 3
  }
]
```

!!! warning "Attribute Validation"
    The `attribute` parameter must match `^[A-Za-z][A-Za-z0-9_]{0,63}$`. Invalid names return a 400 error.

---

### Fraud Ring Detection

Detect cyclic patterns (rings) in the entity graph — entities connected in a loop, which is a strong indicator of coordinated fraud.

```
GET /v1/analytics/fraud-rings?tenant_id=acme&min_size=3
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tenant_id` | string | required | Tenant identifier |
| `min_size` | int | 3 | Minimum ring members. Rings are capped at 6 nodes. |

**Response:**

```json
[
  {
    "ring_members": ["user-1", "user-2", "device-shared"],
    "ring_size": 3,
    "relationships": ["USED", "SHARED_WITH", "USED"],
    "aggregate_tags": ["sdk:vpn", "fraud"]
  }
]
```

---

### Entity Risk Score

Compute a composite risk score (0–100) for a single entity based on its graph neighborhood.

```
GET /v1/analytics/entity-risk?tenant_id=acme&entity_id=user-42
```

**Response:**

```json
{
  "entity_id": "user-42",
  "risk_score": 55,
  "risk_factors": [
    "connected_flagged:2",
    "medium_community:4",
    "shared_devices:1",
    "moderate_connectivity:6"
  ],
  "connected_flagged_count": 2,
  "community_size": 4
}
```

**Risk scoring factors:**

| Factor | Points | Condition |
|---|---|---|
| Own high-risk tags | +30 | Entity has tags: `fraud`, `suspicious`, `flagged`, `blocked`, `chargedback` |
| Connected flagged neighbors | +10 each (max 25) | Neighbors with high-risk tags |
| Large community (≥ 5) | +15 | Part of a large connected component |
| Medium community (≥ 3) | +8 | Part of a medium connected component |
| Shared devices | +10 each (max 20) | Other entities sharing the same `device_id` |
| High connectivity (≥ 10) | +10 | Many direct connections |
| Moderate connectivity (≥ 5) | +5 | Several direct connections |

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `tarka2026` | Neo4j password (same as compose `NEO4J_AUTH` user/password suffix) |
| `API_KEYS` | _(empty)_ | Comma-separated API keys. Empty = no auth |

---

## Entity Resolution

The Graph Service performs entity resolution through deterministic property matching. When the Decision API processes an event, it automatically:

1. **Upserts an Account node** with the `entity_id` as `external_id`
2. **Upserts a Device node** (if `device_context` is present) with `device_id` as `external_id`
3. **Creates a USED relationship** between Account → Device
4. **Upserts a Session node** (if `session_id` is present)
5. **Creates a USED relationship** between Account → Session

Over time, this builds a graph where:

- Multiple accounts sharing a device are connected through the Device node
- Multiple devices used by the same account fan out from the Account node
- Sessions link activity across time

---

## Example Cypher Queries

Run these directly in the Neo4j Browser at `http://localhost:7474`.

**Find all entities connected to a user within 2 hops:**

```cypher
MATCH path = (root {tenant_id: "acme", external_id: "user-42"})-[*1..2]-(n)
WHERE n.tenant_id = "acme"
RETURN path
```

**Find accounts sharing the same device:**

```cypher
MATCH (a1:Account {tenant_id: "acme"})-[:USED]->(d:Device)<-[:USED]-(a2:Account)
WHERE a1.external_id <> a2.external_id
RETURN a1.external_id, d.external_id AS device, a2.external_id
```

**Find entities with high-risk tags:**

```cypher
MATCH (n {tenant_id: "acme"})
WHERE ANY(t IN COALESCE(n.tags, []) WHERE t IN ["fraud", "suspicious", "blocked"])
RETURN n.external_id, labels(n), n.tags
```

**Count entities per label type:**

```cypher
MATCH (n {tenant_id: "acme"})
RETURN labels(n) AS type, count(n) AS count
ORDER BY count DESC
```
