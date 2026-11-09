# Evaluate device graph seed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One evaluate write path stores device reputation and a `TRANSACTED` party edge, and `make demo` fills tenant `demo` by posting that path.

**Architecture:** `build_evaluate_objects` gains the `TRANSACTED` link. A small helper reads and writes `DeviceIntelligenceStore` so `pipeline.py` only calls it. The demo seed stops posting `/v1/entities` and `/v1/links`. `up_desk.sh` runs the seed on a cold start. `up_product.sh` does not.

**Tech Stack:** Python 3.11, pytest, pytest-asyncio, existing `DeviceIntelligenceStore` Redis client, existing `build_evaluate_objects`.

## Global Constraints

- Rust packs still decide. This slice does not let device reputation allow, deny, or review.
- Missing reputation is an absent feature. It is not score `0` and not a default risk of `50`.
- A deny on this request is not `is_fraud_confirmed`. Late labels stay out of this slice.
- Shadow duplicate traffic does not read or write device intelligence, matching the fingerprint skip.
- No demo branch inside evaluate or graph handlers.
- The seed writes only tenant `demo`. It gains no `--tenant` flag.
- `make product` / `scripts/oss/up_product.sh` does not call the seed.
- The edge evaluate writes for a device stays `USED_DEVICE`. Do not rename it to `USES_DEVICE`.
- Do not edit `_graph_upsert`. It already posts the object and link lists from `build_evaluate_objects`.
- Do not poll the graph from the seed.
- Do not change `DeviceReputation.calculate_risk_score` or the store's internal starting `base_reputation` of `50`.

---

### Task 1: `TRANSACTED` counterparty edge

**Files:**
- Modify: `packages/shared-core/tarka_shared/decision_graph_payload.py` (insert before `return objects, links` at the end of `build_evaluate_objects`, currently line 410)
- Test: `packages/shared-core/tests/test_decision_graph_payload.py`

**Interfaces:**
- Consumes: `_trim`, `_obj`, `objects`, `links`, `person_id`, payload key `counterparty_entity_id`
- Produces: link `{"from_external_id": person_id, "to_external_id": counterparty, "relationship": "TRANSACTED"}` and a Person object for the counterparty when that external id is not already in `objects`

- [ ] **Step 1: Write the failing test**

Append to `packages/shared-core/tests/test_decision_graph_payload.py`:

```python
def test_counterparty_entity_id_emits_transacted_edge():
    mod = _load_payload()
    objects, links = mod.build_evaluate_objects(
        trace_id="tr-pay",
        entity_id="fraud_frank",
        event_type="payment",
        payload={
            "amount": 1200,
            "currency": "USD",
            "counterparty_entity_id": "mule_ivan",
        },
    )
    assert _link(links, "TRANSACTED", src="fraud_frank", dst="mule_ivan")
    persons = [o["external_id"] for o in objects if o["entity_type"] == "Person"]
    assert persons.count("mule_ivan") == 1
    assert "fraud_frank" in persons


def test_counterparty_blank_same_or_missing_emits_no_transacted_edge():
    mod = _load_payload()
    cases = [
        {},
        {"counterparty_entity_id": ""},
        {"counterparty_entity_id": "   "},
        {"counterparty_entity_id": "fraud_frank"},
    ]
    for payload in cases:
        _objects, links = mod.build_evaluate_objects(
            trace_id="tr-pay",
            entity_id="fraud_frank",
            event_type="payment",
            payload=payload,
        )
        assert _link(links, "TRANSACTED") is None
```

`_link` is already defined in that test file. Do not add a second copy.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest packages/shared-core/tests/test_decision_graph_payload.py::test_counterparty_entity_id_emits_transacted_edge packages/shared-core/tests/test_decision_graph_payload.py::test_counterparty_blank_same_or_missing_emits_no_transacted_edge -q`

Expected: FAIL because no `TRANSACTED` link is produced (`assert _link(...)` is None / assertion error).

- [ ] **Step 3: Write minimal implementation**

In `build_evaluate_objects`, immediately before `return objects, links`:

```python
    counterparty = _trim(pl.get("counterparty_entity_id"))
    if counterparty and counterparty != person_id:
        if not any(o["external_id"] == counterparty for o in objects):
            _obj(counterparty, "Person", {})
        links.append(
            {
                "from_external_id": person_id,
                "to_external_id": counterparty,
                "relationship": "TRANSACTED",
            }
        )
```

Do not edit `_graph_upsert` in `services/decision-api/src/decision_api/main.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest packages/shared-core/tests/test_decision_graph_payload.py::test_counterparty_entity_id_emits_transacted_edge packages/shared-core/tests/test_decision_graph_payload.py::test_counterparty_blank_same_or_missing_emits_no_transacted_edge packages/shared-core/tests/test_decision_graph_payload.py::test_build_evaluate_objects_login_device_context -q`

Expected: PASS. The login test still sees `USED_DEVICE`.

- [ ] **Step 5: Commit**

```bash
git add packages/shared-core/tarka_shared/decision_graph_payload.py packages/shared-core/tests/test_decision_graph_payload.py
git commit -m "$(cat <<'EOF'
Add a TRANSACTED edge when evaluate names a counterparty.

EOF
)"
```

---

### Task 2: Device-intelligence helper

**Files:**
- Create: `services/decision-api/src/decision_api/device_intelligence_eval.py`
- Test: `services/decision-api/tests/test_device_intelligence_eval.py`

**Interfaces:**
- Consumes: `DeviceIntelligenceStore` methods `get_device_reputation`, `update_device_reputation(tenant_id, device_id, decision, is_fraud_confirmed=False)`, `record_biometrics`, `record_consortium_device`, `record_device_ip_velocity`. `DeviceReputation.calculate_risk_score()`.
- Produces:
  - `async def apply_prior_device_reputation(features: dict, degrade_tags: list[str], *, store, tenant_id: str, device_id: str | None, shadow: bool) -> None`
  - `async def record_device_intelligence_outcome(degrade_tags: list[str], *, store, tenant_id: str, entity_id: str, device_id: str | None, decision: str, signals: dict | None, ip: str | None, shadow: bool) -> None`
  - `def device_ip_for_velocity(payload: dict | None, signals: dict | None) -> str`

- [ ] **Step 1: Write the failing test**

Create `services/decision-api/tests/test_device_intelligence_eval.py`:

```python
from __future__ import annotations

import pytest

from decision_api.device_intelligence import DeviceReputation
from decision_api.device_intelligence_eval import (
    apply_prior_device_reputation,
    device_ip_for_velocity,
    record_device_intelligence_outcome,
)


class _Store:
    def __init__(self, reputation=None, boom: bool = False, client=object()):
        self._client = client
        self.reputation = reputation
        self.boom = boom
        self.updated = None
        self.biometrics = None
        self.consortium = None
        self.ip_velocity = None

    async def get_device_reputation(self, tenant_id, device_id):
        if self.boom:
            raise RuntimeError("redis down")
        return self.reputation

    async def update_device_reputation(self, tenant_id, device_id, decision, is_fraud_confirmed=False):
        self.updated = (tenant_id, device_id, decision, is_fraud_confirmed)
        return self.reputation

    async def record_biometrics(self, tenant_id, entity_id, device_id, behavior):
        self.biometrics = behavior

    async def record_consortium_device(self, device_id, tenant_id, entity_id):
        self.consortium = (device_id, tenant_id, entity_id)
        return {}

    async def record_device_ip_velocity(self, device_id, ip, tenant_id):
        self.ip_velocity = (device_id, ip, tenant_id)
        return {}


def _rep() -> DeviceReputation:
    return DeviceReputation(
        device_id="dev-1",
        tenant_id="demo",
        total_evaluations=1,
        fraud_confirmed_count=0,
        review_count=0,
        deny_count=1,
        base_reputation=50.0,
        velocity_risk=50.0,
        cross_tenant_appearances=0,
        known_fraud_tenants=set(),
        first_seen=1.0,
        last_seen=2.0,
    )


@pytest.mark.asyncio
async def test_prior_row_sets_reputation_score_only():
    rep = _rep()
    features: dict = {}
    tags: list[str] = []
    await apply_prior_device_reputation(
        features, tags, store=_Store(reputation=rep), tenant_id="demo", device_id="dev-1", shadow=False
    )
    assert features == {"device_reputation_score": rep.calculate_risk_score()}
    assert tags == []


@pytest.mark.asyncio
async def test_missing_row_client_and_shadow_leave_features_unset():
    for store, shadow, device_id in (
        (_Store(reputation=None), False, "dev-1"),
        (_Store(client=None, reputation=_rep()), False, "dev-1"),
        (_Store(reputation=_rep()), True, "dev-1"),
        (_Store(reputation=_rep()), False, None),
        (_Store(reputation=_rep()), False, "  "),
    ):
        features: dict = {}
        tags: list[str] = []
        await apply_prior_device_reputation(
            features, tags, store=store, tenant_id="demo", device_id=device_id, shadow=shadow
        )
        assert features == {}
        assert tags == []


@pytest.mark.asyncio
async def test_read_error_tags_and_does_not_set_score():
    features: dict = {}
    tags: list[str] = []
    await apply_prior_device_reputation(
        features, tags, store=_Store(boom=True), tenant_id="demo", device_id="dev-1", shadow=False
    )
    assert features == {}
    assert tags == ["device_intelligence:unavailable"]


def test_device_ip_payload_wins():
    assert device_ip_for_velocity({"ip_address": " 203.0.113.8 "}, {"ip_address": "198.51.100.1"}) == "203.0.113.8"
    assert device_ip_for_velocity({}, {"ip_address": "198.51.100.1"}) == "198.51.100.1"
    assert device_ip_for_velocity(None, None) == ""


@pytest.mark.asyncio
async def test_record_outcome_is_not_a_fraud_label_and_skips_flat_signals():
    store = _Store()
    tags: list[str] = []
    await record_device_intelligence_outcome(
        tags,
        store=store,
        tenant_id="demo",
        entity_id="fraud_frank",
        device_id="dev-1",
        decision="deny",
        signals={"is_vpn": True, "is_emulator": True},
        ip="203.0.113.8",
        shadow=False,
    )
    assert store.updated == ("demo", "dev-1", "deny", False)
    assert store.biometrics is None
    assert store.consortium == ("dev-1", "demo", "fraud_frank")
    assert store.ip_velocity == ("dev-1", "203.0.113.8", "demo")
    assert tags == []


@pytest.mark.asyncio
async def test_record_biometrics_only_for_nested_groups_and_write_errors_tag():
    store = _Store()
    tags: list[str] = []
    await record_device_intelligence_outcome(
        tags,
        store=store,
        tenant_id="demo",
        entity_id="u1",
        device_id="dev-1",
        decision="allow",
        signals={"typing": {"avg_inter_key_ms": 80}},
        ip=None,
        shadow=False,
    )
    assert store.biometrics == {"typing": {"avg_inter_key_ms": 80}}
    assert store.ip_velocity is None

    class _Boom(_Store):
        async def update_device_reputation(self, *args, **kwargs):
            raise RuntimeError("redis down")

    tags2: list[str] = []
    await record_device_intelligence_outcome(
        tags2,
        store=_Boom(),
        tenant_id="demo",
        entity_id="u1",
        device_id="dev-1",
        decision="review",
        signals=None,
        ip=None,
        shadow=False,
    )
    assert tags2 == ["device_intelligence:unavailable"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest services/decision-api/tests/test_device_intelligence_eval.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'decision_api.device_intelligence_eval'`.

If pytest cannot import `decision_api` at all, rerun from `services/decision-api` after `pip install -e .` in that directory (existing package layout, `where = ["src"]`). Do not add a new dependency.

- [ ] **Step 3: Write minimal implementation**

Create `services/decision-api/src/decision_api/device_intelligence_eval.py`:

```python
from __future__ import annotations

from typing import Any

_BIOMETRIC_GROUPS = ("typing", "mouse", "session", "bot_indicators")
_TAG = "device_intelligence:unavailable"


def device_ip_for_velocity(payload: dict | None, signals: dict | None) -> str:
    candidates: list[Any] = []
    if isinstance(payload, dict):
        candidates.append(payload.get("ip_address"))
    if isinstance(signals, dict):
        candidates.append(signals.get("ip_address"))
    for raw in candidates:
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def _device_id(device_id: str | None) -> str:
    if not isinstance(device_id, str):
        return ""
    return device_id.strip()


def _armed(store: Any, device_id: str | None, shadow: bool) -> str:
    if shadow or getattr(store, "_client", None) is None:
        return ""
    return _device_id(device_id)


def _mark(degrade_tags: list[str]) -> None:
    if _TAG not in degrade_tags:
        degrade_tags.append(_TAG)


async def apply_prior_device_reputation(
    features: dict,
    degrade_tags: list[str],
    *,
    store: Any,
    tenant_id: str,
    device_id: str | None,
    shadow: bool,
) -> None:
    did = _armed(store, device_id, shadow)
    if not did:
        return
    try:
        row = await store.get_device_reputation(tenant_id, did)
    except Exception:
        _mark(degrade_tags)
        return
    if row is None:
        return
    features["device_reputation_score"] = row.calculate_risk_score()


async def record_device_intelligence_outcome(
    degrade_tags: list[str],
    *,
    store: Any,
    tenant_id: str,
    entity_id: str,
    device_id: str | None,
    decision: str,
    signals: dict | None,
    ip: str | None,
    shadow: bool,
) -> None:
    did = _armed(store, device_id, shadow)
    if not did:
        return
    try:
        await store.update_device_reputation(
            tenant_id, did, decision, is_fraud_confirmed=False
        )
        if isinstance(signals, dict) and any(
            isinstance(signals.get(key), dict) for key in _BIOMETRIC_GROUPS
        ):
            await store.record_biometrics(tenant_id, entity_id, did, signals)
        await store.record_consortium_device(did, tenant_id, entity_id)
        if isinstance(ip, str) and ip.strip():
            await store.record_device_ip_velocity(did, ip.strip(), tenant_id)
    except Exception:
        _mark(degrade_tags)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest services/decision-api/tests/test_device_intelligence_eval.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/decision-api/src/decision_api/device_intelligence_eval.py services/decision-api/tests/test_device_intelligence_eval.py
git commit -m "$(cat <<'EOF'
Record device reputation around evaluate without scoring from an empty store.

EOF
)"
```

---

### Task 3: Wire the helper into evaluate

**Files:**
- Modify: `services/decision-api/src/decision_api/main.py` (the `if redis_tags._client:` block around lines 933-941)
- Modify: `services/decision-api/src/decision_api/evaluate/pipeline.py` (`run_evaluate_decision`)
- Test: `services/decision-api/tests/test_device_intelligence_eval.py` (append one source test)

**Interfaces:**
- Consumes: `apply_prior_device_reputation`, `record_device_intelligence_outcome`, `device_ip_for_velocity` from Task 2. Singleton `device_intelligence` in `decision_api.device_intelligence`.
- Produces: `device_intelligence.set_client(redis_tags._client)` beside `fingerprint_store.set_client`. Pipeline calls the read after `merge_device_context_into_features`. Pipeline calls the write immediately after `decision` is assigned (`allow` / `review` / `deny` around lines 1297-1304), and before the whitelist `return EvaluateResponse` (`decision="allow"`) and the blacklist `return EvaluateResponse` (`decision="deny"`).

- [ ] **Step 1: Write the failing test**

Append to `services/decision-api/tests/test_device_intelligence_eval.py`:

```python
from pathlib import Path


def test_pipeline_and_lifespan_call_the_helper():
    root = Path(__file__).resolve().parents[1]
    pipeline = (root / "src/decision_api/evaluate/pipeline.py").read_text()
    main = (root / "src/decision_api/main.py").read_text()
    assert "apply_prior_device_reputation" in pipeline
    assert pipeline.count("record_device_intelligence_outcome") >= 3
    assert "device_intelligence.set_client(redis_tags._client)" in main
```

`parents[1]` from `services/decision-api/tests/` is `services/decision-api`. Confirm that before relying on it. If the test file lives in `tests/`, `parents[1]` is the service root. That matches this path.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest services/decision-api/tests/test_device_intelligence_eval.py::test_pipeline_and_lifespan_call_the_helper -q`

Expected: FAIL on the `apply_prior_device_reputation` assertion.

- [ ] **Step 3: Write minimal implementation**

In `main.py`, inside the existing `if redis_tags._client:` block, after `entity_link_store.set_client(redis_tags._client)`:

```python
        from decision_api.device_intelligence import device_intelligence

        device_intelligence.set_client(redis_tags._client)
```

In `pipeline.py`, near the other evaluate imports inside `run_evaluate_decision` (the function already imports siblings inline), add:

```python
    from decision_api.device_intelligence import device_intelligence
    from decision_api.device_intelligence_eval import (
        apply_prior_device_reputation,
        device_ip_for_velocity,
        record_device_intelligence_outcome,
    )
```

Add this nested coroutine after `degrade_tags: list[str] = []` (the list already exists at that point; define the coroutine just after `shadow_request` is known and `degrade_tags` exists):

```python
    async def _record_device_intel(decision: str) -> None:
        signals = (
            body.device_context.signals
            if body.device_context and isinstance(body.device_context.signals, dict)
            else None
        )
        payload = body.payload if isinstance(body.payload, dict) else None
        ip = device_ip_for_velocity(payload, signals)
        await record_device_intelligence_outcome(
            degrade_tags,
            store=device_intelligence,
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            device_id=body.device_context.device_id if body.device_context else None,
            decision=decision,
            signals=signals,
            ip=ip or None,
            shadow=shadow_request,
        )
```

Immediately before the whitelist `return EvaluateResponse(` (decision allow, about line 407):

```python
            await _record_device_intel("allow")
```

Immediately before the blacklist `return EvaluateResponse(` (decision deny):

```python
            await _record_device_intel("deny")
```

Immediately after `merge_device_context_into_features(features, body.device_context)`:

```python
        await apply_prior_device_reputation(
            features,
            degrade_tags,
            store=device_intelligence,
            tenant_id=body.tenant_id,
            device_id=body.device_context.device_id if body.device_context else None,
            shadow=shadow_request,
        )
```

Immediately after the block that assigns `decision` to `"deny"`, `"review"`, or `"allow"` (the `force_deny_from_degrade_tags` / threshold block), before `reasons: list[str] = []`:

```python
        await _record_device_intel(decision)
```

That write runs after `force_deny_from_degrade_tags` has already chosen the decision. `device_intelligence:unavailable` is not in that function's tag list, so a failed write cannot flip this request to deny.

Do not add a demo-tenant branch.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest services/decision-api/tests/test_device_intelligence_eval.py -q`

Expected: PASS, including the helper tests from Task 2.

- [ ] **Step 5: Commit**

```bash
git add services/decision-api/src/decision_api/main.py services/decision-api/src/decision_api/evaluate/pipeline.py services/decision-api/tests/test_device_intelligence_eval.py
git commit -m "$(cat <<'EOF'
Call device intelligence on the evaluate path when Redis is configured.

EOF
)"
```

---

### Task 4: Seed posts evaluate only

**Files:**
- Modify: `scripts/seed_demo_data.py`
- Test: `tests/test_seed_demo_device_graph.py`

**Interfaces:**
- Consumes: `TENANT_ID`, `_mule_transactions`, `MULES`, `require_seed_planes` (new), `main`
- Produces: mule evaluate bodies whose `entity_id` is `referred_by` and whose `payload["counterparty_entity_id"]` is the mule id. No `seed_graph`. `require_seed_planes(*, decision_ok: bool, graph_ok: bool) -> None` raises `SystemExit(1)` when either flag is false.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seed_demo_device_graph.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "scripts" / "seed_demo_data.py"


def _load():
    spec = importlib.util.spec_from_file_location("seed_demo_data", SEED)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_tenant_and_mule_counterparty_and_no_direct_graph_posts():
    mod = _load()
    text = SEED.read_text()
    assert mod.TENANT_ID == "demo"
    assert not hasattr(mod, "seed_graph")
    assert "/v1/entities" not in text
    assert "/v1/links" not in text
    txns = mod._mule_transactions()
    assert txns
    frank = [t for t in txns if t["entity_id"] == "fraud_frank"]
    gina = [t for t in txns if t["entity_id"] == "fraud_gina"]
    assert frank and {t["payload"]["counterparty_entity_id"] for t in frank} == {"mule_ivan"}
    assert gina and {t["payload"]["counterparty_entity_id"] for t in gina} == {"mule_jane"}
    for txn in txns:
        assert txn["tenant_id"] == "demo"
        assert txn["entity_id"] != txn["payload"]["counterparty_entity_id"]
        assert "amount" in txn["payload"]
        assert txn["payload"]["currency"] == "USD"
    fraud = mod._fraudster_transactions()
    shared = [
        t for t in fraud
        if t["entity_id"] in {"fraud_frank", "fraud_gina"}
    ]
    assert shared
    assert {t["device_context"]["device_id"] for t in shared} == {"dev_emulator_003"}


def test_require_seed_planes_exits_without_decision_or_graph():
    mod = _load()
    with pytest.raises(SystemExit) as denied:
        mod.require_seed_planes(decision_ok=False, graph_ok=True)
    assert denied.value.code == 1
    with pytest.raises(SystemExit) as no_graph:
        mod.require_seed_planes(decision_ok=True, graph_ok=False)
    assert no_graph.value.code == 1
    mod.require_seed_planes(decision_ok=True, graph_ok=True)


def test_decision_url_default_stays_unprefixed():
    text = SEED.read_text()
    assert 'default="http://localhost:8000"' in text
    assert "--tenant" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_seed_demo_device_graph.py -q`

Expected: FAIL. `seed_graph` still exists, mule `entity_id` is the mule, `/v1/entities` is still in the file, `require_seed_planes` is missing.

- [ ] **Step 3: Write minimal implementation**

Add this function next to the other helpers in `scripts/seed_demo_data.py`:

```python
def require_seed_planes(*, decision_ok: bool, graph_ok: bool) -> None:
    if not decision_ok:
        print("Aborting — decision-api must be running.", file=sys.stderr)
        raise SystemExit(1)
    if not graph_ok:
        print("Aborting — graph-service must be running.", file=sys.stderr)
        raise SystemExit(1)
```

Replace `_mule_transactions` with:

```python
def _mule_transactions() -> list[dict]:
    """Sender evaluate: fraudster pays the mule. Graph edge comes from counterparty_entity_id."""
    txns: list[dict] = []
    random.seed(184)
    for mule in MULES:
        sender = mule["referred_by"]
        for i in range(3):
            txns.append(
                {
                    "tenant_id": TENANT_ID,
                    "event_type": "payment",
                    "entity_id": sender,
                    "session_id": f"sess_{sender}_to_{mule['id']}_{i}",
                    "payload": {
                        "amount": round(random.uniform(1000, 3000), 2),
                        "currency": "USD",
                        "merchant": "WireTransfer",
                        "counterparty_entity_id": mule["id"],
                        "ip_address": f"45.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}",
                        "timestamp": _ts(random.uniform(1, 24)),
                    },
                    "metadata": {
                        "source": "demo_seed",
                        "category": "mule_transfer",
                        "referred_by": mule["referred_by"],
                    },
                }
            )
    return txns
```

Delete `seed_graph`, `_graph_entities`, and `_graph_links`.

Replace the body of `main` after `async with httpx.AsyncClient(...)` with this control flow. Decision-api health still exits on failure inside the loop below. Case-api no longer shares that loop.

```python
        print("Checking service health ...")
        decision_ok = False
        try:
            r = await client.get(f"{decision_url}/v1/health")
            r.raise_for_status()
            decision_ok = True
            print("  ✓ decision-api is up")
        except httpx.HTTPError as exc:
            print(f"  ✗ decision-api at {decision_url} is not reachable: {exc}")

        case_ok = False
        try:
            r = await client.get(f"{case_url}/v1/health")
            r.raise_for_status()
            case_ok = True
            print("  ✓ case-api is up")
        except httpx.HTTPError as exc:
            print(f"  – case-api at {case_url} is not reachable: {exc}")

        graph_ok = False
        try:
            r = await client.get(f"{graph_url}/v1/health")
            if r.status_code == 200:
                graph_ok = True
                print("  ✓ graph-service is up")
        except httpx.HTTPError as exc:
            print(f"  ✗ graph-service at {graph_url} is not reachable: {exc}")

        require_seed_planes(decision_ok=decision_ok, graph_ok=graph_ok)

        ingress_available = False
        try:
            r = await client.get(f"{ingress_url}/v1/health")
            if r.status_code == 200:
                ingress_available = True
                print("  ✓ integration-ingress is up")
        except httpx.HTTPError:
            print("  – integration-ingress not available (skipping integration seed)")

        if case_ok and not force:
            if await _already_seeded(client, case_url):
                print(
                    "\nDemo data already exists for tenant 'demo'. Use --force to re-seed (additive)."
                )
                return

        print()
        print("Seeding decisions ...")
        trace_ids = await seed_decisions(client, decision_url)
        print(f"  Collected {len(trace_ids)} trace IDs\n")

        if case_ok:
            print("Seeding investigation cases ...")
            await seed_cases(client, case_url, trace_ids)
            print()
            print("Seeding disputes ...")
            await seed_disputes(client, case_url, trace_ids)
            print()
        else:
            print("Skipping cases and disputes (case-api unavailable)\n")

        print("Seeding entity lists ...")
        await seed_entity_lists(client, decision_url)
        print()

        if ingress_available:
            print("Seeding integrations ...")
            await seed_integrations(client, ingress_url)
            print()
        else:
            print("Skipping integrations seed (service unavailable)\n")

        print("Done! Demo data seeded for tenant 'demo'.")
        print(f"  Decision API: {decision_url}/docs")
        print(f"  Case API:     {case_url}/docs")
        print(f"  Graph API:    {graph_url}/docs")
```

Delete the old graph-seed block that calls `seed_graph`. Do not add `--tenant`. Do not change the `--decision-url` default `http://localhost:8000`. `graph_url` stays a parameter and is only used for the health check and the final print.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_seed_demo_device_graph.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_demo_data.py tests/test_seed_demo_device_graph.py
git commit -m "$(cat <<'EOF'
Seed the demo tenant through evaluate instead of a second graph writer.

EOF
)"
```

---

### Task 5: Cold-start `make demo` runs the seed

**Files:**
- Modify: `scripts/oss/up_desk.sh` (only the cold path, immediately before the final `exec python3 "$ROOT/scripts/oss/walk_receipts.py"`)
- Test: `tests/test_seed_demo_device_graph.py` (append)

**Interfaces:**
- Consumes: `CORE_PORT`, `GRAPH_PORT`, `scripts/seed_demo_data.py` from Task 4
- Produces: one seed invocation on the cold path with `--decision-url "http://127.0.0.1:${CORE_PORT}/decisions"` and `--graph-url "http://127.0.0.1:${GRAPH_PORT}"`. The early already-healthy `exec` of `walk_receipts.py` stays above it and does not call the seed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_seed_demo_device_graph.py`:

```python
def test_demo_cold_path_seeds_and_product_does_not():
    desk = (ROOT / "scripts" / "oss" / "up_desk.sh").read_text()
    product = (ROOT / "scripts" / "oss" / "up_product.sh").read_text()
    assert "seed_demo_data.py" not in product
    assert desk.count("seed_demo_data.py") == 1
    seed_at = desk.index("seed_demo_data.py")
    first_walk = desk.index("walk_receipts.py")
    assert first_walk < seed_at
    assert desk.index("walk_receipts.py", seed_at) > seed_at
    assert '--decision-url "http://127.0.0.1:${CORE_PORT}/decisions"' in desk
    assert '--graph-url "http://127.0.0.1:${GRAPH_PORT}"' in desk
```

The first `walk_receipts.py` in `up_desk.sh` is the already-healthy short-circuit (`exec python3 .../walk_receipts.py` near the top). The seed must appear after that occurrence and before the final walk exec.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_seed_demo_device_graph.py::test_demo_cold_path_seeds_and_product_does_not -q`

Expected: FAIL because `up_desk.sh` does not contain `seed_demo_data.py`.

- [ ] **Step 3: Write minimal implementation**

In `scripts/oss/up_desk.sh`, replace the final line:

```bash
exec python3 "$ROOT/scripts/oss/walk_receipts.py"
```

with:

```bash
python3 "$ROOT/scripts/seed_demo_data.py" \
  --decision-url "http://127.0.0.1:${CORE_PORT}/decisions" \
  --graph-url "http://127.0.0.1:${GRAPH_PORT}"
exec python3 "$ROOT/scripts/oss/walk_receipts.py"
```

Do not edit the earlier already-healthy branch that execs `walk_receipts.py` and skips compose. Do not edit `scripts/oss/up_product.sh`.

There are two `exec python3 "$ROOT/scripts/oss/walk_receipts.py"` lines. Change only the one at the bottom of the file, after the frontend probe.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_seed_demo_device_graph.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/oss/up_desk.sh tests/test_seed_demo_device_graph.py
git commit -m "$(cat <<'EOF'
Run the demo seed on a cold make demo, not on make product.

EOF
)"
```
