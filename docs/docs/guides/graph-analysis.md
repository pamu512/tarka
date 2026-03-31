# Graph Analysis Guide

The Graph Service builds an entity graph that connects accounts, devices, sessions, payments, and other entities through their relationships. This guide shows how to use graph analytics endpoints and Cypher queries to detect fraud rings, propagate risk, and investigate suspicious clusters.

---

## Entity Resolution

Tarka performs automatic entity resolution during the decision flow. Every time the Decision API evaluates an event, it upserts entities and links into the graph:

```
POST /v1/decisions/evaluate
  │
  ├── Upsert Account node (entity_id → external_id)
  ├── Upsert Device node  (device_context.device_id → external_id)
  ├── Link Account → Device (USED)
  ├── Upsert Session node (session_id → external_id)
  └── Link Account → Session (USED)
```

Over time, the graph reveals hidden connections:

- **Shared devices** — Two accounts using the same `device_id` are connected through the Device node.
- **Session chains** — Repeated sessions from the same account create temporal activity links.
- **Cross-entity links** — KYC verification, referral relationships, and payment links can be added by the Integration Ingress service.

### Default Entity Types

| Entity Type | Description | Linked From |
|---|---|---|
| `Account` | User/merchant account | Decision API `entity_id` |
| `Device` | Physical or virtual device | SDK `device_context.device_id` |
| `Person` | Individual identity | Integration Ingress (KYC) |
| `Payment` | Transaction record | Custom integration |
| `Document` | ID document | Integration Ingress (KYC) |
| `Custom` | Catch-all for custom entities | Any service |

### Default Relationship Types

| Relationship | Description |
|---|---|
| `USED` | Account used a device or session |
| `SHARED_WITH` | Entity shared an attribute with another |
| `REFERRED` | Referral relationship |
| `KYC_VERIFIED_BY` | KYC document verification link |
| `OWNS` | Ownership relationship |
| `RELATED` | Generic fallback relationship |

---

## Community Detection

Communities are connected components in the graph — groups of entities that are all reachable from each other. A single legitimate user typically forms a small community (1 account + 1–2 devices). Large communities often indicate coordinated fraud.

### API Call

```bash
curl -s "http://localhost:8001/v1/analytics/communities?tenant_id=acme&min_size=3" \
  | python -m json.tool
```

### Interpreting Results

```json
[
  {
    "community_id": 0,
    "member_count": 12,
    "member_ids": ["user-1", "user-2", "user-3", "device-a", "device-b", ...],
    "member_labels": ["Account", "Device"],
    "shared_attributes": ["sdk:vpn", "sdk:bot", "velocity:high_1h"]
  }
]
```

**Red flags:**

- `member_count` > 10 with multiple Account nodes → possible fraud ring
- `shared_attributes` containing `sdk:bot` or `sdk:emulator` → automated fraud
- Multiple accounts sharing very few devices → account farming

### Investigation Workflow

1. Run community detection with `min_size=3`
2. For each large community, check the `shared_attributes` for risk tags
3. Drill into specific entities with the subgraph endpoint
4. Use risk propagation to score untagged entities in the cluster

---

## Risk Propagation

Risk propagation starts from a known-risky entity and spreads a risk score outward through the graph. Each hop reduces the score by a decay factor. This surfaces entities that are connected to known fraud but haven't been directly flagged yet.

### How It Works

```
Known Fraudster (risk = 100)
  │
  ├── 1 hop: device-abc     → 100 × 0.5 = 50
  │     │
  │     └── 2 hops: user-99 → 100 × 0.5² = 25
  │           │
  │           └── 3 hops: device-xyz → 100 × 0.5³ = 12.5
  │
  └── 1 hop: session-abc    → 50
```

### API Call

```bash
curl -s "http://localhost:8001/v1/analytics/risk-propagation?\
tenant_id=acme&entity_id=user-42&depth=3&decay=0.5" \
  | python -m json.tool
```

### Tuning Parameters

| Parameter | Effect |
|---|---|
| `depth=1` | Only immediate neighbors |
| `depth=3` (default) | Typical investigation radius |
| `depth=5` (max) | Deep investigation, may include distant false positives |
| `decay=0.3` | Aggressive drop-off — only very close entities get high scores |
| `decay=0.5` (default) | Balanced propagation |
| `decay=0.8` | Slow decay — risk spreads far into the network |

### When to Use

- After confirming an entity as fraudulent, propagate risk to find accomplices
- During investigation, identify entities that share infrastructure with known bad actors
- Automated: trigger risk propagation from workflows on `decision_deny` events

---

## Shared Attribute Analysis

Find entities that share a specific property value. This is useful for detecting:

- **Device sharing** — Multiple accounts using the same device fingerprint
- **IP clustering** — Multiple accounts originating from the same IP
- **Card reuse** — Same payment card hash across different accounts

### API Call

```bash
curl -s "http://localhost:8001/v1/analytics/shared-attributes?\
tenant_id=acme&attribute=device_id&min_shared=2" \
  | python -m json.tool
```

### Supported Attributes

Any property stored on a graph node can be queried. Common attributes:

| Attribute | Use Case |
|---|---|
| `device_id` | Shared device detection |
| `ip_address` | IP clustering |
| `email` | Email reuse across accounts |
| `phone` | Phone number sharing |
| `card_hash` | Payment card reuse |

---

## Fraud Ring Detection

Fraud rings are cyclic patterns — a group of entities connected in a loop (A → B → C → A). These indicate coordinated schemes where multiple fake accounts are used together.

### API Call

```bash
curl -s "http://localhost:8001/v1/analytics/fraud-rings?tenant_id=acme&min_size=3" \
  | python -m json.tool
```

### Response

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

Rings are capped at 6 nodes to keep queries tractable. The `aggregate_tags` field collects all tags from ring members, making it easy to assess overall risk.

---

## Entity Risk Scoring

The composite entity risk endpoint combines multiple graph signals into a single 0–100 score for any entity.

### API Call

```bash
curl -s "http://localhost:8001/v1/analytics/entity-risk?\
tenant_id=acme&entity_id=user-42" \
  | python -m json.tool
```

### Scoring Breakdown

| Factor | Points | Condition |
|---|---|---|
| Own high-risk tags | +30 | Entity has tags: `fraud`, `suspicious`, `flagged`, `blocked`, `chargedback` |
| Connected flagged neighbors | +10 each (max 25) | Direct neighbors with high-risk tags |
| Large community (≥ 5 members) | +15 | Part of a large connected component |
| Medium community (≥ 3 members) | +8 | Part of a medium connected component |
| Shared devices | +10 each (max 20) | Other entities with the same `device_id` |
| High connectivity (≥ 10 links) | +10 | Many direct relationships |
| Moderate connectivity (≥ 5 links) | +5 | Several direct relationships |

---

## Investigation Workflow

Here is a complete workflow for investigating a suspicious entity using graph analytics:

### Step 1: Check Entity Risk

```bash
curl -s "http://localhost:8001/v1/analytics/entity-risk?\
tenant_id=acme&entity_id=user-suspicious" | python -m json.tool
```

If the risk score is elevated, proceed to deeper analysis.

### Step 2: Explore the Neighborhood

```bash
curl -s "http://localhost:8001/v1/subgraph?\
entity_id=user-suspicious&tenant_id=acme&depth=2" | python -m json.tool
```

Map out what the entity is connected to — devices, sessions, other accounts.

### Step 3: Check for Shared Devices

```bash
curl -s "http://localhost:8001/v1/analytics/shared-attributes?\
tenant_id=acme&attribute=device_id&min_shared=2" | python -m json.tool
```

See if any devices are shared with other entities.

### Step 4: Detect Communities

```bash
curl -s "http://localhost:8001/v1/analytics/communities?\
tenant_id=acme&min_size=3" | python -m json.tool
```

Check if the entity belongs to a suspicious cluster.

### Step 5: Scan for Fraud Rings

```bash
curl -s "http://localhost:8001/v1/analytics/fraud-rings?\
tenant_id=acme&min_size=3" | python -m json.tool
```

Look for cyclic patterns involving the entity.

### Step 6: Propagate Risk

If fraud is confirmed, propagate risk to connected entities:

```bash
curl -s "http://localhost:8001/v1/analytics/risk-propagation?\
tenant_id=acme&entity_id=user-suspicious&depth=3&decay=0.5" | python -m json.tool
```

### Step 7: Tag and Create Cases

For each entity with a high propagated risk score, update tags and create investigation cases:

```bash
curl -X POST http://localhost:8001/v1/entities/user-connected/tags \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "acme", "tags": ["suspicious", "linked-to-fraud-ring"]}'

curl -X POST http://localhost:8002/v1/cases \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "title": "Connected to confirmed fraud ring",
    "entity_id": "user-connected",
    "priority": "high"
  }'
```

---

## Direct Cypher Queries

For ad-hoc investigation, connect directly to Neo4j Browser at `http://localhost:7474` and run Cypher queries.

### Find the shortest path between two entities

```cypher
MATCH path = shortestPath(
  (a {tenant_id: "acme", external_id: "user-1"})-[*]-(b {tenant_id: "acme", external_id: "user-2"})
)
RETURN path
```

### Find all entities within 3 hops of a fraudster

```cypher
MATCH (root {tenant_id: "acme", external_id: "user-fraudster"})
MATCH path = (root)-[*1..3]-(n)
WHERE n.tenant_id = "acme"
RETURN DISTINCT n.external_id, labels(n), n.tags,
       min(length(path)) AS distance
ORDER BY distance
```

### Find accounts sharing more than 2 devices

```cypher
MATCH (a1:Account {tenant_id: "acme"})-[:USED]->(d:Device)<-[:USED]-(a2:Account)
WHERE a1.external_id < a2.external_id
WITH a1, a2, count(DISTINCT d) AS shared_devices
WHERE shared_devices >= 2
RETURN a1.external_id, a2.external_id, shared_devices
ORDER BY shared_devices DESC
```

### Find isolated clusters with risk tags

```cypher
MATCH (n {tenant_id: "acme"})
WHERE ANY(t IN COALESCE(n.tags, []) WHERE t STARTS WITH "sdk:")
OPTIONAL MATCH (n)-[r]-(neighbor)
WHERE neighbor.tenant_id = "acme"
RETURN n.external_id, labels(n), n.tags,
       count(DISTINCT neighbor) AS connections
ORDER BY connections DESC
```
