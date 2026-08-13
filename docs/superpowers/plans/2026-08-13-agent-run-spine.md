# AgentRun Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One AgentRun store for chat, Shadow ingest, and trend tick, plus graph-gated lifecycle proposals and human trend promote that only marks `gitops_ready=true`.

**Architecture:** investigation-agent keeps SQLite AgentRun. Orchestrator and decision-api fire-and-forget `POST /v1/internal/agent-runs`. Chat may return `graph_missing=true`. `propose_case_status` and human promote reject unless snapshot `freshness.graph == "present"`. Human promote never installs live Wasm.

**Tech Stack:** FastAPI, SQLite (`agent_run_store`, `trend_store`), httpx, existing `backtest_before_promote_gate`, React SPA (`ShadowChatSidebar`, `OpsCalibration`).

## Global Constraints

- Decision-api / rules remain sole allow/deny authority.
- AI never auto-resolves a case and never auto-promotes Wasm (`wasm_ready` stays false).
- Missing sources are `freshness=missing` — never invented.
- Ingest / tick must not fail because investigation-agent is down (2s timeout, log warning, never raise).
- Chat persist failure → `503` (no un-audited copilot claim).
- Human promote 200 means `gitops_ready=true`, status `PENDING_VALIDATION`, `wasm_ready=false`.
- Tick / missing actor / missing `backtest_job_id` → `409 never_auto_promote`.
- No new service. No SQLite→Postgres. No live LLM in CI.
- `source` ∈ `chat` | `shadow` | `trend`.
- Allowed proposal targets: `OPEN`, `UNDER_REVIEW`, `PENDING_ACTION`, `RESOLVED_FRAUD`, `RESOLVED_LEGIT`. Never `RESOLVED_AUTO`.

## File map

| File | Responsibility |
|------|----------------|
| `services/investigation-agent/src/investigation_agent/agent_run_store.py` | Persist `source`; derive `graph_missing` on read |
| `services/investigation-agent/src/investigation_agent/case_status_proposals.py` | New: SQLite proposals next to AgentRun |
| `services/investigation-agent/src/investigation_agent/main.py` | Internal POST, chat `graph_missing`/`503`, proposal HTTP, tool dispatch |
| `services/investigation-agent/src/investigation_agent/tools.py` | `propose_case_status` definition + dispatch |
| `services/investigation-agent/src/investigation_agent/tool_validation.py` | Args for `propose_case_status` |
| `services/investigation-agent/src/investigation_agent/integration_contract.py` | Bump `1.2.0` → `1.3.0`; family map |
| `services/orchestrator/transaction_ingest.py` | `maybe_enqueue_agent_run` after Shadow |
| `services/decision-api/src/decision_api/trend_agent_api.py` | Tick enqueue + human promote |
| `services/analytics/src/analytics/trend_store.py` | `gitops_ready`, `agent_run_id`, `mark_draft_gitops_ready` |
| `frontend/src/api/client.ts` | `graph_missing`, proposals, `trendPromoteDraft` |
| `frontend/src/components/CaseView/ShadowChatSidebar.tsx` | Banner + confirm |
| `frontend/src/pages/OpsCalibration.tsx` | Promote control disabled without job id |

---

### Task 1: AgentRun `source` + `graph_missing`

**Files:**
- Modify: `services/investigation-agent/src/investigation_agent/agent_run_store.py`
- Modify: `services/investigation-agent/src/investigation_agent/main.py` (`_persist_and_attach_agent_run`, `agent_run_get`)
- Test: `services/investigation-agent/tests/test_agent_run_and_context.py`

**Interfaces:**
- Consumes: existing `persist_agent_run`, `assemble_context_snapshot` (`freshness.graph`)
- Produces: `persist_agent_run(..., source: str = "chat") -> str`; GET/chat include `graph_missing: bool` and `source: str`

- [ ] **Step 1: Write the failing tests**

Add to `test_agent_run_and_context.py`:

```python
def test_graph_missing_and_source_on_get(data_dir: Path) -> None:
    from investigation_agent import agent_run_store
    from investigation_agent.context_assembler import assemble_context_snapshot

    snap = assemble_context_snapshot(tenant_id="ten-a", case_id="c9", case_payload={"id": "c9"})
    rid = agent_run_store.persist_agent_run(
        turn_id="turn-1",
        tenant_id="ten-a",
        analyst_id="analyst-1",
        case_id="c9",
        context_snapshot=snap,
        source="shadow",
    )
    got = agent_run_store.get_agent_run(run_id=rid, tenant_id="ten-a")
    assert got is not None
    assert got["source"] == "shadow"
    assert got["graph_missing"] is True

    snap_g = assemble_context_snapshot(
        tenant_id="ten-a",
        case_id="c9",
        case_payload={"id": "c9"},
        graph_neighborhood={"vertices": [{"id": "device:1"}]},
    )
    rid2 = agent_run_store.persist_agent_run(
        turn_id="turn-2",
        tenant_id="ten-a",
        analyst_id="analyst-1",
        context_snapshot=snap_g,
        source="chat",
    )
    got2 = agent_run_store.get_agent_run(run_id=rid2, tenant_id="ten-a")
    assert got2 is not None
    assert got2["graph_missing"] is False


def test_chat_includes_graph_missing(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ALLOWED_ANALYSTS", "*")
    from investigation_agent.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        chat = client.post(
            "/v1/chat",
            json={
                "tenant_id": "t-chat",
                "analyst_id": "analyst-chat",
                "case_id": "case-chat-1",
                "messages": [{"role": "user", "content": "Summarize this case risk"}],
            },
        )
        assert chat.status_code == 200, chat.text
        assert chat.json()["graph_missing"] is True


def test_chat_persist_failure_is_503(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ALLOWED_ANALYSTS", "*")
    from investigation_agent import agent_run_store
    from investigation_agent.main import app
    from fastapi.testclient import TestClient

    def _boom(**kwargs):  # noqa: ANN003
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(agent_run_store, "persist_agent_run", _boom)
    with TestClient(app) as client:
        chat = client.post(
            "/v1/chat",
            json={
                "tenant_id": "t-chat",
                "analyst_id": "analyst-chat",
                "case_id": "case-chat-1",
                "messages": [{"role": "user", "content": "x"}],
            },
        )
        assert chat.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core:../collaboration-chat-bridge/src \
  pytest tests/test_agent_run_and_context.py::test_graph_missing_and_source_on_get \
         tests/test_agent_run_and_context.py::test_chat_includes_graph_missing \
         tests/test_agent_run_and_context.py::test_chat_persist_failure_is_503 -v
```

Expected: FAIL (`source` / `graph_missing` KeyError or persist kwargs unexpected; chat 200 not 503).

- [ ] **Step 3: Minimal implementation**

In `agent_run_store.py`:

- `_ALLOWED_SOURCES = frozenset({"chat", "shadow", "trend"})`
- In `_init_schema`, after CREATE TABLE, migrate:

```python
cols = {r[1] for r in c.execute("PRAGMA table_info(agent_runs)").fetchall()}
if "source" not in cols:
    c.execute("ALTER TABLE agent_runs ADD COLUMN source TEXT NOT NULL DEFAULT 'chat'")
```

- `persist_agent_run(..., source: str = "chat")`: `src = (source or "chat").strip().lower()`; if `src not in _ALLOWED_SOURCES`: `src = "chat"`. Include `source` in INSERT (add column to INSERT list).
- `_row_to_dict`: include `"source": row[14] if len(row) > 14 else "chat"` and:

```python
def graph_missing_from_snapshot(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return True
    return (snapshot.get("freshness") or {}).get("graph") != "present"
```

`"graph_missing": graph_missing_from_snapshot(json.loads(row[12] or "{}"))`

- Update `_SELECT` to include `source`.

In `main.py` `_persist_and_attach_agent_run`: wrap persist in try/except `Exception` → `raise HTTPException(status_code=503, detail="agent_run_persist_failed")`. After success set `out["graph_missing"] = agent_run_store.graph_missing_from_snapshot(snapshot)` and pass `source="chat"`.

`agent_run_get` already returns the store dict (will include the new keys).

- [ ] **Step 4: Run tests to verify they pass**

Same pytest command as Step 2. Expected: PASS.

Also run existing:

```bash
PYTHONPATH=src:../shared:../../packages/shared-core:../collaboration-chat-bridge/src \
  pytest tests/test_agent_run_and_context.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/investigation-agent/src/investigation_agent/agent_run_store.py \
        services/investigation-agent/src/investigation_agent/main.py \
        services/investigation-agent/tests/test_agent_run_and_context.py
git commit -m "Expose AgentRun source and graph_missing on persist/get/chat."
```

---

### Task 2: `POST /v1/internal/agent-runs`

**Files:**
- Modify: `services/investigation-agent/src/investigation_agent/main.py`
- Test: `services/investigation-agent/tests/test_agent_run_and_context.py`

**Interfaces:**
- Consumes: `_require_internal_hook_auth`, `persist_agent_run(..., source=)`
- Produces: `POST /v1/internal/agent-runs` → `{ok, run_id, graph_missing, source}`

- [ ] **Step 1: Write the failing test**

```python
def test_internal_agent_run_post_round_trip(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_INTERNAL_SECRET", "brief-secret")
    from investigation_agent.context_assembler import assemble_context_snapshot
    from investigation_agent.main import app
    from fastapi.testclient import TestClient

    snap = assemble_context_snapshot(
        tenant_id="t1",
        entity_id="ent-1",
        graph_neighborhood={"vertices": [{"id": "ip:9"}]},
    )
    with TestClient(app) as client:
        denied = client.post(
            "/v1/internal/agent-runs",
            json={
                "turn_id": "ingest:tx-1",
                "tenant_id": "t1",
                "analyst_id": "system:shadow",
                "source": "shadow",
                "entity_ids": ["ent-1"],
                "context_snapshot": snap,
                "claims": [{"text": "device hub", "source": "shadow", "evidence_ids": ["graph:x"]}],
            },
            headers={"x-internal-secret": "wrong"},
        )
        assert denied.status_code == 401

        r = client.post(
            "/v1/internal/agent-runs",
            json={
                "turn_id": "ingest:tx-1",
                "tenant_id": "t1",
                "analyst_id": "system:shadow",
                "source": "shadow",
                "entity_ids": ["ent-1"],
                "context_snapshot": snap,
                "claims": [{"text": "device hub", "source": "shadow", "evidence_ids": ["graph:x"]}],
            },
            headers={"x-internal-secret": "brief-secret"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["source"] == "shadow"
        assert body["graph_missing"] is False
        rid = body["run_id"]
        g = client.get(f"/v1/agent-runs/{rid}", params={"tenant_id": "t1"})
        assert g.status_code == 200
        assert g.json()["source"] == "shadow"
        assert g.json()["claims"][0]["evidence_ids"] == ["graph:x"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core:../collaboration-chat-bridge/src \
  pytest tests/test_agent_run_and_context.py::test_internal_agent_run_post_round_trip -v
```

Expected: FAIL 404 on POST.

- [ ] **Step 3: Minimal implementation**

In `main.py` next to `CaseBriefBody`:

```python
class InternalAgentRunBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    turn_id: str = Field(..., min_length=1, max_length=128)
    tenant_id: str = Field(..., min_length=1, max_length=128)
    analyst_id: str = Field(default="system", max_length=128)
    case_id: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    trace_ids: list[str] = Field(default_factory=list)
    source: str = "chat"
    claims: list[dict[str, Any]] = Field(default_factory=list)
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    prompt_version: str = ""
    model: str = ""
    agent_build: str = ""
```

```python
@app.post("/v1/internal/agent-runs")
async def internal_agent_run(request: Request, body: InternalAgentRunBody):
    _require_internal_hook_auth(request)
    src = (body.source or "chat").strip().lower()
    if src not in {"chat", "shadow", "trend"}:
        raise HTTPException(status_code=400, detail="invalid_source")
    try:
        rid = agent_run_store.persist_agent_run(
            turn_id=body.turn_id.strip(),
            tenant_id=body.tenant_id.strip(),
            analyst_id=(body.analyst_id or "system").strip(),
            case_id=body.case_id,
            entity_ids=body.entity_ids,
            trace_ids=body.trace_ids,
            prompt_version=body.prompt_version,
            model=body.model,
            agent_build=body.agent_build,
            tool_calls=body.tool_calls,
            claims=body.claims,
            context_snapshot=body.context_snapshot,
            source=src,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="agent_run_persist_failed") from None
    row = agent_run_store.get_agent_run(run_id=rid, tenant_id=body.tenant_id.strip())
    return {
        "ok": True,
        "run_id": rid,
        "source": src,
        "graph_missing": bool(row and row.get("graph_missing")),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Same pytest as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/investigation-agent/src/investigation_agent/main.py \
        services/investigation-agent/tests/test_agent_run_and_context.py
git commit -m "Add internal AgentRun ingest for Shadow and trend callers."
```

---

### Task 3: Orchestrator fire-and-forget AgentRun

**Files:**
- Modify: `services/orchestrator/transaction_ingest.py`
- Test: `services/orchestrator/tests/test_trend_watch_enqueue.py` (add tests in this file; same fire-and-forget pattern)

**Interfaces:**
- Consumes: `POST /v1/internal/agent-runs` from Task 2
- Produces: `async def maybe_enqueue_agent_run(*, tenant_id: str, entity_id: str, turn_id: str, source: str, context_snapshot: dict[str, Any], claims: list[dict[str, Any]] | None = None, http: httpx.AsyncClient | None = None) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `test_trend_watch_enqueue.py`:

```python
@pytest.mark.asyncio
async def test_maybe_enqueue_agent_run_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATION_AGENT_URL", "http://inv.test")
    monkeypatch.setenv("INVESTIGATION_INTERNAL_SECRET", "s3")
    monkeypatch.setenv("AGENT_RUN_INGEST_TIMEOUT_SEC", "2")
    from transaction_ingest import maybe_enqueue_agent_run

    http = AsyncMock()
    http.post = AsyncMock(return_value=MagicMock())
    await maybe_enqueue_agent_run(
        http=http,
        tenant_id="ten-a",
        entity_id="ent-1",
        turn_id="ingest:tx-1",
        source="shadow",
        context_snapshot={"freshness": {"graph": "present"}},
        claims=[{"text": "hub", "source": "shadow", "evidence_ids": ["graph:1"]}],
    )
    http.post.assert_awaited()
    args, kwargs = http.post.await_args
    assert args[0].endswith("/v1/internal/agent-runs")
    assert kwargs["json"]["source"] == "shadow"
    assert kwargs["headers"]["x-internal-secret"] == "s3"


@pytest.mark.asyncio
async def test_maybe_enqueue_agent_run_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVESTIGATION_AGENT_URL", "http://inv.test")
    from transaction_ingest import maybe_enqueue_agent_run

    http = AsyncMock()
    http.post = AsyncMock(side_effect=RuntimeError("down"))
    await maybe_enqueue_agent_run(
        http=http,
        tenant_id="ten-a",
        entity_id="ent-1",
        turn_id="ingest:tx-1",
        source="shadow",
        context_snapshot={},
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/orchestrator
pytest tests/test_trend_watch_enqueue.py::test_maybe_enqueue_agent_run_posts \
       tests/test_trend_watch_enqueue.py::test_maybe_enqueue_agent_run_swallows_errors -v
```

Expected: FAIL `ImportError: cannot import name maybe_enqueue_agent_run`.

- [ ] **Step 3: Minimal implementation**

In `transaction_ingest.py` next to `maybe_enqueue_trend_watch`:

```python
def _agent_run_ingest_timeout_sec() -> float:
    raw = (os.environ.get("AGENT_RUN_INGEST_TIMEOUT_SEC") or "2").strip()
    try:
        v = float(raw)
    except ValueError:
        return 2.0
    return v if v > 0 else 2.0


async def maybe_enqueue_agent_run(
    *,
    tenant_id: str,
    entity_id: str,
    turn_id: str,
    source: str,
    context_snapshot: dict[str, Any],
    claims: list[dict[str, Any]] | None = None,
    http: httpx.AsyncClient | None = None,
) -> None:
    """Fire-and-forget AgentRun ingest — never raises to callers."""
    base = (os.environ.get("INVESTIGATION_AGENT_URL") or "").strip()
    if not base or not tenant_id.strip():
        return
    url = f"{base.rstrip('/')}/v1/internal/agent-runs"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    secret = (os.environ.get("INVESTIGATION_INTERNAL_SECRET") or "").strip()
    if secret:
        headers["x-internal-secret"] = secret
    payload = {
        "turn_id": (turn_id or "")[:128],
        "tenant_id": tenant_id.strip(),
        "analyst_id": f"system:{source}"[:128],
        "entity_ids": [entity_id.strip()] if entity_id.strip() else [],
        "source": source,
        "context_snapshot": context_snapshot if isinstance(context_snapshot, dict) else {},
        "claims": list(claims or []),
    }
    timeout = _agent_run_ingest_timeout_sec()
    try:
        if http is not None:
            await http.post(url, json=payload, headers=headers, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as client:
                await client.post(url, json=payload, headers=headers)
    except Exception:
        logger.warning(
            "orchestrator_agent_run_enqueue_failed tenant_id=%s turn_id=%s",
            tenant_id,
            turn_id,
            exc_info=True,
        )
```

In the ingest path after Shadow returns (same try-block neighborhood as `maybe_enqueue_trend_watch`, ~line 885): if `shadow_data` is a dict (including timeout fallback), build snapshot from existing `graph_context` / prime payload already on the request — **do not invent graph**. If a graph dict is present, pass it into a tiny local snapshot:

```python
from investigation_agent.context_assembler import assemble_context_snapshot  # DON'T
```

Orchestrator must **not** import investigation-agent. Inline:

```python
graph_obj = gctx if isinstance(gctx, dict) and gctx else None
# gctx is whatever this request already assembled for Shadow (build_prime_shadow_graph_context result).
snap = {
    "schema_id": "tarka.context_snapshot/v1",
    "tenant_id": tenant_for_watch,
    "entity_id": str(entity_for_watch),
    "freshness": {"graph": "present" if graph_obj else "missing"},
    "keys_present": ["graph"] if graph_obj else [],
    "artifacts": [],
}
await maybe_enqueue_agent_run(
    tenant_id=tenant_for_watch,
    entity_id=str(entity_for_watch),
    turn_id=f"ingest:{tid}",
    source="shadow",
    context_snapshot=snap,
    claims=[{"text": str(shadow_data.get("agent_notes") or "shadow")[:2000], "source": "shadow", "evidence_ids": []}],
)
```

Wrap that call in the existing `except Exception` that already logs `orchestrator_trend_watch_hook_failed`, or a sibling try/except that never fails ingest.

If `tenant_for_watch` is empty, skip (same as watch).

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/orchestrator
pytest tests/test_trend_watch_enqueue.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/transaction_ingest.py \
        services/orchestrator/tests/test_trend_watch_enqueue.py
git commit -m "Fire-and-forget Shadow AgentRuns from ingest without blocking."
```

---

### Task 4: Trend tick AgentRun + `agent_run_id` on drafts

**Files:**
- Modify: `services/analytics/src/analytics/trend_store.py`
- Modify: `services/decision-api/src/decision_api/trend_agent_api.py`
- Test: `services/decision-api/tests/test_trend_agent_api.py`

**Interfaces:**
- Consumes: Task 2 POST
- Produces: `insert_draft_rule(..., agent_run_id: str | None = None)`; tick POSTs a run then stores `agent_run_id` on the draft. Tick still never calls promote.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_tick_enqueues_agent_run_and_survives_agent_down(
    trend_http: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_AGENT_URL", "http://inv.test")
    posted: list[dict] = []

    async def _fake_post(url, json=None, headers=None, timeout=None):  # noqa: ANN001
        posted.append({"url": url, "json": json})
        raise RuntimeError("down")

    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    # Direct evaluate still 200; enqueue helper must not raise.
    from decision_api.trend_agent_api import maybe_enqueue_trend_agent_run

    await maybe_enqueue_trend_agent_run(
        tenant_id="ten-a",
        entity_id="ent-1",
        turn_id="trend:ent-1",
        context_snapshot={"freshness": {"graph": "missing"}},
        claims=[],
    )
```

Add a unit test that `insert_draft_rule` round-trips `agent_run_id` once the column exists — will fail until schema migrates.

In `services/analytics/tests/test_trend_agent.py` or the HTTP test file:

```python
def test_draft_stores_agent_run_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_AGENT_DATA_DIR", str(tmp_path))
    from analytics import trend_store

    trend_store.reset_connection_for_tests()
    did = trend_store.insert_draft_rule(
        tenant_id="t",
        entity_id="e",
        rule_package={"wasm_ready": False, "status": "PENDING_VALIDATION"},
        envelope={},
        agent_run_id="run-abc",
    )
    row = trend_store.get_draft_rule(tenant_id="t", draft_id=did)
    assert row is not None
    assert row["agent_run_id"] == "run-abc"
    assert row["gitops_ready"] is False
    trend_store.reset_connection_for_tests()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../../packages/shared-core:../analytics/src:../.. \
  pytest tests/test_trend_agent_api.py::test_tick_enqueues_agent_run_and_survives_agent_down -v
```

```bash
cd services/analytics
PYTHONPATH=src \
  pytest tests/test_trend_agent.py -k draft_stores_agent_run_id -v
```

Expected: FAIL missing function / unexpected kwarg `agent_run_id`.

- [ ] **Step 3: Minimal implementation**

`trend_store.py` `_init_schema`: after createscript, PRAGMA-migrate:

```python
cols = {r[1] for r in c.execute("PRAGMA table_info(trend_draft_rules)").fetchall()}
if "agent_run_id" not in cols:
    c.execute("ALTER TABLE trend_draft_rules ADD COLUMN agent_run_id TEXT")
if "gitops_ready" not in cols:
    c.execute("ALTER TABLE trend_draft_rules ADD COLUMN gitops_ready INTEGER NOT NULL DEFAULT 0")
if "backtest_job_id" not in cols:
    c.execute("ALTER TABLE trend_draft_rules ADD COLUMN backtest_job_id TEXT")
```

Update INSERT, `get_draft_rule`, `list_pending_drafts` to include `agent_run_id`, `gitops_ready` (bool), `backtest_job_id`.

`insert_draft_rule(..., agent_run_id: str | None = None)`.

In `trend_agent_api.py`:

```python
async def maybe_enqueue_trend_agent_run(
    *,
    tenant_id: str,
    entity_id: str,
    turn_id: str,
    context_snapshot: dict[str, Any],
    claims: list[dict[str, Any]] | None = None,
) -> str | None:
    """Fire-and-forget; return run_id if the agent responded, else None. Never raise."""
    base = (os.environ.get("INVESTIGATION_AGENT_URL") or "").strip()
    if not base or not tenant_id.strip():
        return None
    url = f"{base.rstrip('/')}/v1/internal/agent-runs"
    headers = {"Content-Type": "application/json"}
    secret = (os.environ.get("INVESTIGATION_INTERNAL_SECRET") or "").strip()
    if secret:
        headers["x-internal-secret"] = secret
    try:
        timeout = float((os.environ.get("AGENT_RUN_INGEST_TIMEOUT_SEC") or "2").strip() or "2")
    except ValueError:
        timeout = 2.0
    payload = {
        "turn_id": turn_id[:128],
        "tenant_id": tenant_id.strip(),
        "analyst_id": "system:trend",
        "entity_ids": [entity_id.strip()] if entity_id.strip() else [],
        "source": "trend",
        "context_snapshot": context_snapshot,
        "claims": list(claims or []),
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            rid = resp.json().get("run_id")
            return str(rid) if rid else None
    except Exception:
        log.warning(
            "trend_agent_run_enqueue_failed tenant_id=%s entity_id=%s",
            tenant_id,
            entity_id,
            exc_info=True,
        )
    return None
```

`trend_agent_api.py` already has `log = logging.getLogger("decision-api.trend")`. Add `import httpx`.

Call after each successful `run_trend_evaluation` in `trend_tick` with `context_snapshot={"freshness": {"entity_velocity": "present", "graph": "missing"}, "keys_present": ["entity_velocity"]}`. If `draft_rule_id` is set and enqueue returns a run id, `trend_store.set_draft_agent_run_id(...)`. On enqueue failure leave `agent_run_id` null. **Never raise.**

Because tick's fake_post raises, the helper must swallow it (test 1).

- [ ] **Step 4: Run tests to verify they pass**

Same commands as Step 2 plus:

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../../packages/shared-core:../analytics/src:../.. \
  pytest tests/test_trend_agent_api.py -v
```

Expected: PASS. Existing promote-without-body test still 409.

- [ ] **Step 5: Commit**

```bash
git add services/analytics/src/analytics/trend_store.py \
        services/analytics/tests/test_trend_agent.py \
        services/decision-api/src/decision_api/trend_agent_api.py \
        services/decision-api/tests/test_trend_agent_api.py
git commit -m "Attach best-effort AgentRuns to trend ticks without failing evaluate."
```

---

### Task 5: `propose_case_status` HIL

**Files:**
- Create: `services/investigation-agent/src/investigation_agent/case_status_proposals.py`
- Modify: `services/investigation-agent/src/investigation_agent/main.py`
- Modify: `services/investigation-agent/src/investigation_agent/tools.py`
- Modify: `services/investigation-agent/src/investigation_agent/tool_validation.py`
- Modify: `services/investigation-agent/src/investigation_agent/integration_contract.py` (`INTEGRATION_CONTRACT_VERSION = "1.3.0"`, `_TOOL_FAMILY["propose_case_status"] = "case"`)
- Test: `services/investigation-agent/tests/test_agent_run_and_context.py`

**Interfaces:**
- Consumes: `graph_missing_from_snapshot`; AgentRun `run_id`
- Produces: `insert_proposal(...) -> str`; `list_proposals(case_id, tenant_id)`; `ack_proposal(proposal_id, tenant_id, status)`; tool `propose_case_status`; `GET /v1/case-status-proposals`; `POST /v1/case-status-proposals/{id}/ack`

- [ ] **Step 1: Write the failing tests**

```python
_ALLOWED = {"OPEN", "UNDER_REVIEW", "PENDING_ACTION", "RESOLVED_FRAUD", "RESOLVED_LEGIT"}


def test_propose_case_status_requires_graph(data_dir: Path) -> None:
    from investigation_agent import agent_run_store, case_status_proposals
    from investigation_agent.context_assembler import assemble_context_snapshot

    snap = assemble_context_snapshot(tenant_id="t1", case_id="c1", case_payload={"id": "c1"})
    rid = agent_run_store.persist_agent_run(
        turn_id="t", tenant_id="t1", analyst_id="a1", case_id="c1", context_snapshot=snap
    )
    with pytest.raises(case_status_proposals.GraphRequiredError):
        case_status_proposals.insert_proposal(
            tenant_id="t1",
            case_id="c1",
            agent_run_id=rid,
            from_status="OPEN",
            to_status="UNDER_REVIEW",
            reason_code="analyst_review",
        )


def test_propose_and_ack_http(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ALLOWED_ANALYSTS", "*")
    from investigation_agent import agent_run_store, case_status_proposals
    from investigation_agent.context_assembler import assemble_context_snapshot
    from investigation_agent.main import app
    from fastapi.testclient import TestClient

    snap = assemble_context_snapshot(
        tenant_id="t1",
        case_id="c1",
        case_payload={"id": "c1"},
        graph_neighborhood={"vertices": [{"id": "u1"}]},
    )
    rid = agent_run_store.persist_agent_run(
        turn_id="t", tenant_id="t1", analyst_id="a1", case_id="c1", context_snapshot=snap
    )
    pid = case_status_proposals.insert_proposal(
        tenant_id="t1",
        case_id="c1",
        agent_run_id=rid,
        from_status="OPEN",
        to_status="UNDER_REVIEW",
        reason_code="analyst_review",
    )
    with TestClient(app) as client:
        listed = client.get(
            "/v1/case-status-proposals", params={"tenant_id": "t1", "case_id": "c1"}
        )
        assert listed.status_code == 200
        assert listed.json()["items"][0]["proposal_id"] == pid
        ack = client.post(
            f"/v1/case-status-proposals/{pid}/ack",
            json={"tenant_id": "t1", "status": "confirmed"},
        )
        assert ack.status_code == 200
        assert ack.json()["status"] == "confirmed"
```

Also add a tool-level test that dispatch with missing graph returns `{"error": "graph_required"}` (HTTP 200 tool error, not case PUT).

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core:../collaboration-chat-bridge/src \
  pytest tests/test_agent_run_and_context.py::test_propose_case_status_requires_graph \
         tests/test_agent_run_and_context.py::test_propose_and_ack_http -v
```

Expected: FAIL import `case_status_proposals`.

- [ ] **Step 3: Minimal implementation**

Create `case_status_proposals.py` using the same `_data_dir` / lock pattern as `agent_run_store` (own table `case_status_proposals` in the **same sqlite file** via `agent_run_store._get_conn()` to avoid a second DB). Prefer calling `agent_run_store._get_conn()` and creating the table in `agent_run_store._init_schema` plus functions in the new module.

Schema:

```sql
CREATE TABLE IF NOT EXISTS case_status_proposals (
  proposal_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  agent_run_id TEXT NOT NULL,
  from_status TEXT NOT NULL,
  to_status TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at REAL NOT NULL
)
```

`insert_proposal`: load run; if missing or `graph_missing` → raise `GraphRequiredError`. If `to_status not in _ALLOWED` or `to_status == "RESOLVED_AUTO"` → `ValueError`. Status starts `pending`.

`ack_proposal`: only `pending` → `confirmed`|`rejected`. Does **not** call orchestrator PUT (SPA does).

HTTP:
- `GET /v1/case-status-proposals?tenant_id=&case_id=`
- `POST /v1/case-status-proposals/{id}/ack` body `{tenant_id, status}`
- GraphRequiredError → `409 {"error": "graph_required"}`

Tool `propose_case_status` in `tools.py`: local function (no httpx) calling `insert_proposal`. Add to `TOOL_DEFINITIONS` + `TOOL_DISPATCH`. Validation: `case_id`, `to_status`, `reason_code`, `agent_run_id`, optional `from_status`.

In `main.py` `_execute_tool` add a branch like other local tools.

Bump `INTEGRATION_CONTRACT_VERSION` to `"1.3.0"`.

Do **not** add `propose_case_status` to `no_graph` disabled set — the tool stays registered and returns `graph_required`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core:../collaboration-chat-bridge/src \
  pytest tests/test_agent_run_and_context.py tests/test_integration_golden_profiles.py -v
```

Expected: PASS (goldens derive `_ALL_TOOLS` from definitions).

- [ ] **Step 5: Commit**

```bash
git add services/investigation-agent/src/investigation_agent/case_status_proposals.py \
        services/investigation-agent/src/investigation_agent/agent_run_store.py \
        services/investigation-agent/src/investigation_agent/main.py \
        services/investigation-agent/src/investigation_agent/tools.py \
        services/investigation-agent/src/investigation_agent/tool_validation.py \
        services/investigation-agent/src/investigation_agent/integration_contract.py \
        services/investigation-agent/tests/test_agent_run_and_context.py
git commit -m "Add graph-gated case status proposals; confirm stays on PUT."
```

---

### Task 6: Human trend promote → `gitops_ready`

**Files:**
- Modify: `services/analytics/src/analytics/trend_store.py`
- Modify: `services/decision-api/src/decision_api/trend_agent_api.py`
- Modify: `docs/superpowers/specs/2026-08-12-ai-productionization-design.md` (honesty line)
- Test: `services/decision-api/tests/test_trend_agent_api.py`

**Interfaces:**
- Consumes: `backtest_before_promote_gate(require_job=True)`, draft `agent_run_id`, GET AgentRun `graph_missing`
- Produces: `mark_draft_gitops_ready(*, tenant_id, draft_id, backtest_job_id, actor_id) -> dict`; POST promote JSON body

- [ ] **Step 1: Write the failing tests**

Keep existing `test_trend_http_evaluate_reject_promote_forbidden` — query-only POST must still be 409 `never_auto_promote`.

Add:

```python
@pytest.mark.asyncio
async def test_human_promote_gitops_ready_not_live(
    trend_http: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from analytics import trend_store

    rows = [
        {
            "metric_key": "sub_1min_velocity",
            "window": "sub_1min",
            "observed": 100.0,
            "baseline_mean": 10.0,
            "baseline_std": 2.0,
        }
    ]
    r = await trend_http.post(
        "/v1/ops/trend/evaluate",
        json={
            "tenant_id": "ten-a",
            "entity_id": "ent-1",
            "window_rows": rows,
            "skip_llm": True,
        },
    )
    draft_id = r.json()["draft_rule_id"]
    trend_store.set_draft_agent_run_id(
        tenant_id="ten-a", draft_id=draft_id, agent_run_id="run-graph"
    )

    async def _fake_get(self, url, **kwargs):  # noqa: ANN001
        class _R:
            status_code = 200

            def json(self):
                return {
                    "run_id": "run-graph",
                    "graph_missing": False,
                    "context_snapshot": {"freshness": {"graph": "present"}},
                }

        return _R()

    import httpx
    monkeypatch.setenv("INVESTIGATION_AGENT_URL", "http://inv.test")
    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    from decision_api.backtest_promote_gate import backtest_before_promote_gate

    def _ok_gate(**kwargs):  # noqa: ANN003
        return {
            "schema_id": "tarka.backtest_before_promote/v1",
            "promote_allowed": True,
            "blockers": [],
            "waived": False,
            "job_id": kwargs.get("job_id"),
            "job_status": "succeeded",
        }

    monkeypatch.setattr(
        "decision_api.trend_agent_api.backtest_before_promote_gate", _ok_gate
    )

    banned = await trend_http.post(
        f"/v1/ops/trend/drafts/{draft_id}/promote",
        params={"tenant_id": "ten-a"},
    )
    assert banned.status_code == 409

    missing_graph = await trend_http.post(
        f"/v1/ops/trend/drafts/{draft_id}/promote",
        json={"tenant_id": "ten-a", "backtest_job_id": "job-1"},
    )
    # first, simulate missing graph
    async def _missing(self, url, **kwargs):  # noqa: ANN001
        class _R:
            status_code = 200

            def json(self):
                return {"run_id": "run-graph", "graph_missing": True}

        return _R()

    monkeypatch.setattr(httpx.AsyncClient, "get", _missing)
    g409 = await trend_http.post(
        f"/v1/ops/trend/drafts/{draft_id}/promote",
        json={"tenant_id": "ten-a", "backtest_job_id": "job-1"},
    )
    assert g409.status_code == 409
    assert g409.json()["detail"]["error"] == "graph_required"

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    ok = await trend_http.post(
        f"/v1/ops/trend/drafts/{draft_id}/promote",
        json={"tenant_id": "ten-a", "backtest_job_id": "job-1"},
    )
    assert ok.status_code == 200, ok.text
    draft = ok.json()["draft"]
    assert draft["status"] == "PENDING_VALIDATION"
    assert draft["gitops_ready"] is True
    assert draft["rule_package"].get("wasm_ready") is False
    assert draft["agent_run_id"] == "run-graph"
```

Split into two tests if the monkeypatch ordering is painful: (1) query-only still 409, (2) graph_required, (3) happy gitops_ready.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../../packages/shared-core:../analytics/src:../.. \
  pytest tests/test_trend_agent_api.py::test_human_promote_gitops_ready_not_live -v
```

Expected: FAIL (promote always 409).

- [ ] **Step 3: Minimal implementation**

`trend_store.mark_draft_gitops_ready(...)`: UPDATE `gitops_ready=1`, `backtest_job_id=?` WHERE pending. Do not change `status`. Do not set `wasm_ready`. Return `get_draft_rule`.

`trend_store.set_draft_agent_run_id(...)`.

Replace `trend_promote_draft_forbidden` with a body model:

```python
class TrendPromoteBody(BaseModel):
    tenant_id: str
    backtest_job_id: str | None = None
```

Logic:

1. If body missing or `not (body.backtest_job_id or "").strip()` → existing `refuse_promote_draft` 409 `never_auto_promote`.
2. Actor = `_user.user_id` (already injected). If you cannot read `_user` → 409 `never_auto_promote`.
3. Load draft; 404 if missing.
4. If no `agent_run_id` or GET run fails or `graph_missing` → 409 `{"error": "graph_required"}`.
5. `gate = backtest_before_promote_gate(job_status=..., metrics_json=..., kill_criteria=..., require_job=True, job_id=body.backtest_job_id)`. If looking up the real job is heavy, for this spec call the gate with `job_status="succeeded"` **only when** a job fetch succeeds; if job not found, blockers include `backtest_job_id_required` / not succeeded → 409 `{error: "backtest_gate", blockers: ...}`. Prefer fetching via existing session `BacktestRun` if `get_session` is easy to add; otherwise monkeypatchable `_load_backtest_job(job_id)` that tests replace. Default implementation: try `uuid.UUID(job_id)` lookup; on failure `promote_allowed=False`.
6. On success `mark_draft_gitops_ready` and return `{ok: True, draft: row}`.

Update posture `honesty` string: tick/auto still 409; human + job + graph may set `gitops_ready`.

Amend `docs/superpowers/specs/2026-08-12-ai-productionization-design.md` philosophy bullet that says promote always 409 — point at the 2026-08-13 spec.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../../packages/shared-core:../analytics/src:../.. \
  pytest tests/test_trend_agent_api.py -v
```

Expected: PASS, including original query-only 409.

- [ ] **Step 5: Commit**

```bash
git add services/analytics/src/analytics/trend_store.py \
        services/decision-api/src/decision_api/trend_agent_api.py \
        services/decision-api/tests/test_trend_agent_api.py \
        docs/superpowers/specs/2026-08-12-ai-productionization-design.md
git commit -m "Allow human trend promote to GitOps-ready without live Wasm."
```

---

### Task 7: SPA banner, proposals, promote control

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/CaseView/ShadowChatSidebar.tsx`
- Modify: `frontend/src/pages/OpsCalibration.tsx`

**Interfaces:**
- Consumes: `graph_missing` on chat/GET run; `GET /v1/case-status-proposals`; existing case status PUT; `POST .../promote` JSON
- Produces: banner when `graph_missing`; confirm button that PUTs then acks; promote input + button disabled without `backtest_job_id`

No new Jest file (spec: no frontend-only tests).

- [ ] **Step 1: Extend client types**

`InvestigationChatResponse` / `getAgentRun`: add `graph_missing?: boolean`.

```typescript
listCaseStatusProposals(caseId: string, tenantId: string) {
  const q = new URLSearchParams({ case_id: caseId, tenant_id: tenantId });
  return request<{ items: Array<{
    proposal_id: string;
    to_status: string;
    reason_code: string;
    status: string;
    agent_run_id: string;
  }> }>(`/api/investigation/v1/case-status-proposals?${q}`);
},
ackCaseStatusProposal(proposalId: string, tenantId: string, status: "confirmed" | "rejected") {
  return request<{ status: string }>(
    `/api/investigation/v1/case-status-proposals/${encodeURIComponent(proposalId)}/ack`,
    { method: "POST", body: JSON.stringify({ tenant_id: tenantId, status }) },
  );
},
```

```typescript
trendPromoteDraft(draftId: string, tenantId: string, backtestJobId: string) {
  return request<{ ok: boolean; draft: Record<string, unknown> }>(
    `/api/decisions/v1/ops/trend/drafts/${encodeURIComponent(draftId)}/promote`,
    {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, backtest_job_id: backtestJobId }),
    },
  );
},
```

Find the existing case status PUT helper in `client.ts` and reuse it for confirm (do not add a second transition API).

- [ ] **Step 2: ShadowChatSidebar**

After a chat response, if `graph_missing`, show a banner: `Graph neighborhood missing — narratives are ungrounded; status changes and promote stay blocked.`

Load proposals for `caseId`. Confirm: call existing status PUT with `to_status` + `reason_code`, then `ackCaseStatusProposal(..., "confirmed")`. If PUT fails, do not ack (proposal stays `pending`).

- [ ] **Step 3: TrendOpsPanel**

Per draft: show `gitops_ready`. Input `backtest_job_id` (local state keyed by draft id). Button `Mark GitOps-ready` **disabled** when `busy || !jobId.trim()`. On click `decisions.trendPromoteDraft`. Query-only promote must never be used.

Copy: `Does not install live Wasm. Status stays PENDING_VALIDATION.`

- [ ] **Step 4: Typecheck / lint the touched frontend files**

```bash
cd frontend && npx tsc --noEmit --pretty false
```

Expected: PASS (or only pre-existing errors unrelated to these files).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts \
        frontend/src/components/CaseView/ShadowChatSidebar.tsx \
        frontend/src/pages/OpsCalibration.tsx
git commit -m "Surface graph-missing, lifecycle HIL confirm, and GitOps-ready promote."
```

---

## Spec coverage

| Spec requirement | Task |
|------------------|------|
| Internal POST AgentRun + GET round-trip `source` | 2 |
| Ingest 200 when agent down | 3 |
| Chat `graph_missing=true` not 409 | 1 |
| Chat persist 503 | 1 |
| Shadow fire-and-forget | 3 |
| Trend tick fire-and-forget + `agent_run_id` | 4 |
| `propose_case_status` 409 without graph | 5 |
| Confirm = PUT then ack | 5, 7 |
| Query-only / tick promote 409 | 6 (existing test kept) |
| Human promote `gitops_ready`, still `PENDING_VALIDATION`, `wasm_ready=false` | 6 |
| Graph required on human promote | 6 |
| SPA banner / disable promote without job | 7 |
| No new service / no auto-resolve / no live Wasm | Global constraints |

## Placeholder / type check

- `graph_missing_from_snapshot`, `maybe_enqueue_agent_run`, `maybe_enqueue_trend_agent_run`, `insert_proposal`, `mark_draft_gitops_ready`, `set_draft_agent_run_id` names are stable across tasks.
- `source` is `chat|shadow|trend` everywhere.
- Promote 200 never sets `wasm_ready=true`.
