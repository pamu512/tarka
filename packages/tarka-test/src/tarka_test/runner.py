"""Load JSON suites, call Decision API evaluate, assert decisions and trace/manifest steps."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import quote

import httpx

from tarka_test.manifest_match import (
    extract_manifest_steps,
    match_expected_steps,
    normalize_keys,
)
from tarka_test.request_builder import build_evaluate_body


@dataclass
class Suite:
    version: int
    base_url: str
    evaluate_path: str
    audit_path_template: str
    defaults: dict[str, Any]
    headers: dict[str, str]
    audit_headers: dict[str, str]
    cases: list[dict[str, Any]]
    insecure_tls: bool = False


@dataclass
class CaseResult:
    case_id: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    trace_id: str | None = None
    status_code: int | None = None


def load_suite_file(path: str) -> Suite:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("suite root must be a JSON object")
    ver = int(raw.get("version", 1))
    if ver != 1:
        raise ValueError(f"unsupported suite version: {ver}")
    base = str(raw.get("base_url") or "http://127.0.0.1:8000").rstrip("/")
    ep = str(raw.get("evaluate_path") or "/v1/decisions/evaluate")
    if not ep.startswith("/"):
        ep = "/" + ep
    audit_tmpl = str(raw.get("audit_path_template") or "/v1/audit/{trace_id}")
    defaults = dict(raw.get("defaults") or {})
    hdr = _string_dict(raw.get("headers"))
    ahdr = _string_dict(raw.get("audit_headers"))
    if not hdr and raw.get("headers") is None:
        pass
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError('suite must contain non-empty "cases" array')
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            raise ValueError(f"cases[{i}] must be an object")
        if not str(c.get("id") or "").strip():
            raise ValueError(f"cases[{i}] must include string field \"id\"")
    insecure = bool(raw.get("insecure_tls") or False)
    return Suite(
        version=ver,
        base_url=base,
        evaluate_path=ep,
        audit_path_template=audit_tmpl,
        defaults=defaults,
        headers=hdr,
        audit_headers=ahdr,
        cases=list(cases),
        insecure_tls=insecure,
    )


def _string_dict(v: Any) -> dict[str, str]:
    if v is None:
        return {}
    if not isinstance(v, Mapping):
        raise ValueError("headers must be a JSON object of strings")
    out: dict[str, str] = {}
    for k, val in v.items():
        out[str(k)] = str(val)
    return out


def _score_ok(actual: float | None, spec: Any) -> tuple[bool, str]:
    if spec is None:
        return True, ""
    if isinstance(spec, (int, float)):
        if actual is None:
            return False, f"expected score {spec}, got null"
        ok = abs(float(actual) - float(spec)) < 1e-6
        return ok, "" if ok else f"expected score {spec}, got {actual}"
    if isinstance(spec, Mapping):
        lo = spec.get("min")
        hi = spec.get("max")
        if actual is None:
            return False, "expected numeric score, got null"
        fa = float(actual)
        if lo is not None and fa < float(lo):
            return False, f"score {fa} below min {lo}"
        if hi is not None and fa > float(hi):
            return False, f"score {fa} above max {hi}"
        return True, ""
    return False, "expected_score must be number or {min,max} object"


def _fetch_audit(
    client: httpx.Client,
    suite: Suite,
    *,
    trace_id: str,
    tenant_id: str,
    detail_level: str,
) -> tuple[int, dict[str, Any] | None, str | None]:
    tid_q = quote(tenant_id, safe="")
    path = suite.audit_path_template.format(trace_id=trace_id)
    if not path.startswith("/"):
        path = "/" + path
    url = f"{suite.base_url}{path}"
    params = {"tenant_id": tenant_id, "detail_level": detail_level}
    headers = {**suite.headers, **suite.audit_headers}
    try:
        r = client.get(url, params=params, headers=headers, timeout=60.0)
    except httpx.HTTPError as e:
        return 0, None, str(e)
    try:
        js = r.json()
    except json.JSONDecodeError:
        js = None
    if isinstance(js, dict):
        return r.status_code, js, None
    return r.status_code, None, "audit response was not a JSON object"


def run_suite(suite: Suite, *, verbose: bool = False) -> list[CaseResult]:
    results: list[CaseResult] = []
    with httpx.Client(timeout=60.0, verify=not suite.insecure_tls) as client:
        for case in suite.cases:
            cid = str(case["id"])
            cr = CaseResult(case_id=cid, ok=True)
            try:
                body = build_evaluate_body(case, suite.defaults)
                tenant_id = str(body["tenant_id"])
                url = f"{suite.base_url}{suite.evaluate_path}"
                hdrs = {**suite.headers}
                if case.get("idempotency_key") is True or (
                    case.get("idempotency_key") is None
                    and str(suite.defaults.get("send_idempotency_key", "")).lower()
                    in {"1", "true", "yes"}
                ):
                    hdrs.setdefault("Idempotency-Key", str(uuid.uuid4()))
                elif isinstance(case.get("idempotency_key"), str):
                    hdrs["Idempotency-Key"] = case["idempotency_key"]

                if verbose:
                    print(f"\n=== case {cid} POST {url}\n{json.dumps(body, indent=2)}")

                r = client.post(url, json=body, headers=hdrs)
                cr.status_code = r.status_code
                if r.status_code >= 400:
                    cr.ok = False
                    cr.errors.append(f"HTTP {r.status_code}: {r.text[:2000]}")
                    results.append(cr)
                    continue

                try:
                    resp = r.json()
                except json.JSONDecodeError:
                    cr.ok = False
                    cr.errors.append("evaluate response was not JSON")
                    results.append(cr)
                    continue

                if not isinstance(resp, dict):
                    cr.ok = False
                    cr.errors.append("evaluate response JSON must be an object")
                    results.append(cr)
                    continue

                tid = resp.get("trace_id")
                cr.trace_id = str(tid) if tid is not None else None

                exp_dec = case.get("expected_decision")
                if exp_dec is not None:
                    act = resp.get("decision")
                    if str(act) != str(exp_dec):
                        cr.ok = False
                        cr.errors.append(
                            f"decision: expected {exp_dec!r}, got {act!r}"
                        )

                score_chk, score_msg = _score_ok(
                    float(resp["score"]) if resp.get("score") is not None else None,
                    case.get("expected_score"),
                )
                if not score_chk:
                    cr.ok = False
                    cr.errors.append(score_msg)

                exp_steps = case.get("expected_trace_steps")
                tv = case.get("trace_verification") or {}
                if exp_steps is not None and isinstance(exp_steps, list):
                    mode = str(tv.get("mode") or "auto").lower()
                    ordered = bool(tv.get("ordered", False))

                    if mode == "skip":
                        pass
                    elif mode == "local_manifest":
                        _verify_local_manifest(
                            case, exp_steps, ordered, cr, suite.defaults
                        )
                    elif mode in {"manifest", "auto"}:
                        outcome = _audit_manifest_step_verification(
                            client,
                            suite,
                            cr,
                            exp_steps,
                            ordered,
                            tenant_id,
                            str(tv.get("audit_detail_level") or "full"),
                        )
                        if outcome == "verified":
                            pass
                        elif outcome == "no_manifest":
                            if mode == "auto" and isinstance(
                                case.get("local_manifest_check"), Mapping
                            ):
                                _verify_local_manifest(
                                    case, exp_steps, ordered, cr, suite.defaults
                                )
                            else:
                                cr.ok = False
                                cr.errors.append(
                                    "evidence_manifest was not returned by audit "
                                    "(Decision API snapshots often omit it unless wired). "
                                    "Use trace_verification.mode=local_manifest with "
                                    "local_manifest_check, or persist manifests server-side."
                                )
                        elif outcome == "forbidden":
                            if mode == "auto" and isinstance(
                                case.get("local_manifest_check"), Mapping
                            ):
                                _verify_local_manifest(
                                    case, exp_steps, ordered, cr, suite.defaults
                                )
                            else:
                                cr.ok = False
                                cr.errors.append(
                                    "audit detail forbidden (403). "
                                    "Grant analyst access or use local_manifest_check."
                                )
                        elif outcome == "mismatch":
                            pass
                        elif outcome.startswith("fetch_error:"):
                            if mode == "auto" and isinstance(
                                case.get("local_manifest_check"), Mapping
                            ):
                                _verify_local_manifest(
                                    case, exp_steps, ordered, cr, suite.defaults
                                )
                            else:
                                cr.ok = False
                                cr.errors.append(outcome)
                        elif outcome == "missing_trace_id":
                            cr.ok = False
                            cr.errors.append(
                                "evaluate response lacked trace_id — cannot audit manifest"
                            )
                        else:
                            cr.ok = False
                            cr.errors.append(f"audit/manifest verification failed: {outcome}")
                    elif mode == "audit_step_trace":
                        _verify_audit_step_trace(
                            client,
                            suite,
                            cr,
                            exp_steps,
                            ordered,
                            tenant_id,
                            str(tv.get("audit_detail_level") or "full"),
                        )
                    else:
                        cr.ok = False
                        cr.errors.append(f"unknown trace_verification.mode: {mode}")

            except Exception as e:
                cr.ok = False
                cr.errors.append(f"{type(e).__name__}: {e}")

            results.append(cr)
    return results


def _verify_local_manifest(
    case: Mapping[str, Any],
    exp_steps: list[Any],
    ordered: bool,
    cr: CaseResult,
    suite_defaults: Mapping[str, Any],
) -> None:
    lm = case.get("local_manifest_check")
    if not isinstance(lm, Mapping):
        cr.ok = False
        cr.errors.append(
            "trace_verification mode local_manifest requires object "
            "\"local_manifest_check\" with rule_json and rule_content_id_hex"
        )
        return
    from tarka_test.local_engine import (
        build_default_data_obj,
        evaluate_manifest_steps_local,
    )

    rule_json = str(lm.get("rule_json") or "")
    rid = str(lm.get("rule_content_id_hex") or "")
    if not rule_json or not rid:
        cr.ok = False
        cr.errors.append("local_manifest_check.rule_json and rule_content_id_hex required")
        return
    fast = bool(lm.get("fast_path", True))
    body = build_evaluate_body(case, dict(suite_defaults))
    data_override = lm.get("data_json")
    if isinstance(data_override, str):
        data_obj = json.loads(data_override)
    elif isinstance(data_override, Mapping):
        data_obj = dict(data_override)
    else:
        data_obj = build_default_data_obj(case, body)
    try:
        steps = evaluate_manifest_steps_local(
            rule_json=rule_json,
            rule_content_id_hex=rid,
            data_obj=data_obj,
            fast_path=fast,
        )
    except RuntimeError as e:
        cr.ok = False
        cr.errors.append(str(e))
        return
    except Exception as e:
        cr.ok = False
        cr.errors.append(f"local evaluate failed: {type(e).__name__}: {e}")
        return
    exp_norm = [normalize_keys(x) for x in exp_steps if isinstance(x, Mapping)]
    ok, msg = match_expected_steps(steps, exp_norm, ordered=ordered)
    if not ok:
        cr.ok = False
        cr.errors.append(f"manifest steps: {msg}")


def _audit_manifest_step_verification(
    client: httpx.Client,
    suite: Suite,
    cr: CaseResult,
    exp_steps: list[Any],
    ordered: bool,
    tenant_id: str,
    detail_level: str,
) -> str:
    """Return verified | no_manifest | forbidden | fetch_error | mismatch."""
    tid = cr.trace_id
    if not tid:
        return "missing_trace_id"

    code, audit, err = _fetch_audit(
        client, suite, trace_id=tid, tenant_id=tenant_id, detail_level=detail_level
    )
    if err:
        return f"fetch_error:{err}"
    if code == 403:
        return "forbidden"
    if code >= 400 or audit is None:
        return f"fetch_error:HTTP {code}"
    em = audit.get("evidence_manifest")
    if not em:
        return "no_manifest"

    steps = extract_manifest_steps(em)
    exp_norm = [normalize_keys(x) for x in exp_steps if isinstance(x, Mapping)]
    ok, msg = match_expected_steps(steps, exp_norm, ordered=ordered)
    if not ok:
        cr.ok = False
        cr.errors.append(f"evidence_manifest trace steps: {msg}")
        return "mismatch"
    return "verified"


def _verify_audit_step_trace(
    client: httpx.Client,
    suite: Suite,
    cr: CaseResult,
    exp_steps: list[Any],
    ordered: bool,
    tenant_id: str,
    detail_level: str,
) -> None:
    tid = cr.trace_id
    if not tid:
        cr.ok = False
        cr.errors.append("missing trace_id")
        return
    code, audit, err = _fetch_audit(
        client, suite, trace_id=tid, tenant_id=tenant_id, detail_level=detail_level
    )
    if err:
        cr.ok = False
        cr.errors.append(err)
        return
    if code >= 400 or not isinstance(audit, dict):
        cr.ok = False
        cr.errors.append(f"audit HTTP {code}")
        return
    st = audit.get("step_trace")
    if not isinstance(st, list):
        cr.ok = False
        cr.errors.append("audit.step_trace missing (need detail_level analyst/full)")
        return
    exp_norm = [normalize_keys(x) for x in exp_steps if isinstance(x, Mapping)]
    ok, msg = match_expected_steps(st, exp_norm, ordered=ordered)
    if not ok:
        cr.ok = False
        cr.errors.append(f"step_trace: {msg}")
