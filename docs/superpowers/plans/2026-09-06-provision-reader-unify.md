# Provision reader unify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. User said `go` — implement in this session.

**Goal:** Named-desk auto-promote and leftover switches resolve through `desk_provision.json`; `TARKA_*` wins; the legacy shadow JSON is not a silent on-switch for those keys.

**Architecture:** Add `observe.auto_promote` + `observe_auto_promote()` / `host_auto_promote(file_flag)` on the existing loader. Tick and GET AND the first-review file flag with the named-desk gate. Caps stay on the legacy file.

**Tech Stack:** Python 3 stdlib, pytest.

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- Empty plane URL = that plane off.
- No `rate` / `baseline_ratio`. No new Rust `velocity_v1`.
- Demo ≠ product. Do not enable auto-promote by default.
- No CRM verbs. No new Slack/email sinks. No second provision system.
- No third-party desk / editor names in published copy. Do not call Tarka OSS.
- Leftover flags already use `leftover_flag` — do not re-wire them.

---

### Task 1: Loader helper (TDD)

**Files:**
- Modify: `services/shared/tests/test_desk_provision.py`
- Modify: `services/shared/desk_provision.py`
- Modify: `infra/deploy/desk_provision.schema.json`
- Modify: `infra/deploy/desk_provision.example.json`

**Interfaces:**
- Produces: `observe_auto_promote() -> bool | None`, `host_auto_promote(file_flag: bool) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
def test_observe_auto_promote_none_without_file(monkeypatch):
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    monkeypatch.delenv("TARKA_AUTO_PROMOTE", raising=False)
    assert observe_auto_promote() is None
    assert host_auto_promote(True) is True
    assert host_auto_promote(False) is False


def test_observe_auto_promote_file_key_and_omitted_default(tmp_path, monkeypatch):
    path = _write(tmp_path, {"schema_id": SCHEMA_ID, "observe": {"auto_promote": True}})
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    monkeypatch.delenv("TARKA_AUTO_PROMOTE", raising=False)
    assert observe_auto_promote() is True
    path2 = _write(tmp_path, {"schema_id": SCHEMA_ID, "profile": "product"}, name="omit.json")
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path2))
    assert observe_auto_promote() is False
    assert host_auto_promote(True) is False


def test_observe_auto_promote_env_wins(tmp_path, monkeypatch):
    path = _write(tmp_path, {"schema_id": SCHEMA_ID, "observe": {"auto_promote": True}})
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    monkeypatch.setenv("TARKA_AUTO_PROMOTE", "0")
    assert observe_auto_promote() is False
    monkeypatch.setenv("TARKA_AUTO_PROMOTE", "1")
    assert observe_auto_promote() is True
    assert host_auto_promote(True) is True
    assert host_auto_promote(False) is False


def test_leftover_flag_ignores_shadow_auto_promote_json(tmp_path, monkeypatch):
    shadow = tmp_path / "shadow_auto_promote_deadbeef.json"
    shadow.write_text(
        json.dumps({"schema_id": "tarka.shadow_auto_promote_provision/v1", "auto_promote": True}),
        encoding="utf-8",
    )
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    monkeypatch.delenv("TARKA_FLAG_MINTS_LEFTOVER", raising=False)
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    assert leftover_flag("TARKA_FLAG_MINTS_LEFTOVER", "flag_mints_leftover") is False
```

- [ ] **Step 2: Run tests — expect FAIL** (`observe_auto_promote` not defined)

Run: `PYTHONPATH=services/shared python3 -m pytest services/shared/tests/test_desk_provision.py -q`

- [ ] **Step 3: Implement helper + schema/example**

`observe.auto_promote` default false on schema and example. Example stays `false`.

```python
def observe_auto_promote() -> bool | None:
    raw = _env_raw("TARKA_AUTO_PROMOTE")
    if raw is not None and raw.strip() != "":
        return _truthy(raw)
    data = load_desk_provision()
    if not data:
        return None
    observe = data.get("observe")
    if isinstance(observe, dict) and "auto_promote" in observe:
        return bool(observe.get("auto_promote"))
    return False


def host_auto_promote(file_flag: bool) -> bool:
    if observe_auto_promote() is False:
        return False
    return bool(file_flag)
```

- [ ] **Step 4: Run tests — expect PASS**

---

### Task 2: Tick + GET host truth (TDD)

**Files:**
- Modify: `services/decision-api/tests/test_shadow_auto_promote.py`
- Modify: `services/decision-api/src/decision_api/shadow_auto_promote.py`
- Modify: `services/decision-api/src/decision_api/rule_api.py` (GET uses public provision)

**Interfaces:**
- Consumes: `host_auto_promote(file_flag: bool) -> bool`
- Produces: `maybe_auto_promote_shadow` no-ops when named-desk is off; GET `auto_promote` is the AND

- [ ] **Step 1: Write the failing tests**

Tick with `desk_provision.observe.auto_promote: false` + file `auto_promote: true` → `not_provisioned`.  
GET after that PUT reports `auto_promote: false`.  
Env `TARKA_AUTO_PROMOTE=0` same.  
Existing file-only tests stay green (no `TARKA_DESK_PROVISION_PATH`).

- [ ] **Step 2: Run — expect FAIL** (tick still promotes)

Run: `cd services/decision-api && PYTHONPATH=src:.:../shared python3 -m pytest tests/test_shadow_auto_promote.py -q -k 'desk_provision or named_desk or env_off'`

- [ ] **Step 3: AND the named-desk gate in `maybe_auto_promote_shadow` and GET**

```python
def public_provision(tenant_id: str) -> dict[str, Any]:
    out = dict(load_provision(tenant_id))
    try:
        from desk_provision import host_auto_promote
    except ImportError:
        return out
    out["auto_promote"] = host_auto_promote(bool(out.get("auto_promote")))
    return out
```

`maybe_auto_promote_shadow`: `if not host_auto_promote(bool(provision.get("auto_promote"))):` → `not_provisioned`.  
GET: `return public_provision(tenant_id)`. PUT still `save_provision`.

- [ ] **Step 4: Run full file — expect PASS**

Run: `cd services/decision-api && PYTHONPATH=src:.:../shared python3 -m pytest tests/test_shadow_auto_promote.py tests/test_shadow_promote_gate_api.py -q`

---

### Task 3: Operator note + PR

**Files:**
- Modify: `docs/docs/guides/clone-demo.md`
- Modify: `docs/docs/guides/shadow-and-ab-testing.md`

Three sentences: leftover switches + auto-promote boolean live in `desk_provision` / `TARKA_*`. Legacy `tarka.shadow_auto_promote_provision/v1` keeps first-review checkbox + leftover caps. File checkbox alone cannot enable when named-desk `observe.auto_promote` is false.

- [ ] Verify loader + shadow tests.
- [ ] Commit, push, PR. Regressions: desk_provision loader, shadow promote gate, leftover env tests.
