"""Tests for decision graph payload builders."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_payload():
    path = Path(__file__).resolve().parents[1] / "tarka_shared" / "decision_graph_payload.py"
    spec = importlib.util.spec_from_file_location("decision_graph_payload", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_evaluate_payload_includes_entities():
    mod = _load_payload()
    payload = mod.build_evaluate_payload(
        tenant_id="t1",
        trace_id="tr-1",
        entity_id="acct-1",
        event_type="payment",
        decision="review",
        score=0.8,
        rule_hits=["velocity_spike"],
        fallback_reason=None,
        payload={"device_id": "dev-9"},
        metadata={},
        decision_log_record={"id": "al-99"},
        shadow_request=False,
    )
    assert payload["kind"] == "evaluate"
    assert payload["outcome"] == "review"
    assert "acct-1" in payload["entity_external_ids"]
    assert "dev-9" in payload["entity_external_ids"]
    assert payload["audit_log_id"] == "al-99"
    types = {o["entity_type"] for o in payload["objects"]}
    assert types == {"Person", "Device", "Payment"}
    rels = {lk["relationship"] for lk in payload["object_links"]}
    assert "USED_DEVICE" in rels
    assert "MADE_PAYMENT" in rels
    assert "RESULTED_IN" not in rels
    assert all(o["properties"].get("last_outcome") == "review" for o in payload["objects"])


def test_build_evaluate_objects_login_device_context():
    mod = _load_payload()
    objects, links = mod.build_evaluate_objects(
        trace_id="tr-login",
        entity_id="buyer-demo",
        event_type="login",
        payload={},
        device_context={"device_id": "buyer-demo-device"},
    )
    types = {o["entity_type"]: o["external_id"] for o in objects}
    assert types["Person"] == "buyer-demo"
    assert types["Device"] == "buyer-demo-device"
    assert types["Login"] == "login:tr-login"
    assert any(lk["relationship"] == "PERFORMED_LOGIN" for lk in links)
    assert any(lk["relationship"] == "USED_DEVICE" for lk in links)


def test_guest_clicks_share_device_and_session_not_person_id():
    """Caller may mint a new entity_id each click. Device + session are the join."""
    mod = _load_payload()
    a, la = mod.build_evaluate_objects(
        trace_id="tr-a",
        entity_id="guest-aaa",
        event_type="login",
        payload={},
        device_context={"device_id": "dev-same", "signals": {"ip": "203.0.113.9"}},
        session_id="sess-1",
    )
    b, lb = mod.build_evaluate_objects(
        trace_id="tr-b",
        entity_id="guest-bbb",
        event_type="login",
        payload={},
        device_context={"device_id": "dev-same", "signals": {"ip": "203.0.113.9"}},
        session_id="sess-1",
    )
    persons = {o["external_id"] for o in a + b if o["entity_type"] == "Person"}
    assert persons == {"guest-aaa", "guest-bbb"}
    devices = {o["external_id"] for o in a + b if o["entity_type"] == "Device"}
    assert devices == {"dev-same"}
    sessions = {o["external_id"] for o in a + b if o["entity_type"] == "Session"}
    assert sessions == {"sess:sess-1"}
    ips = {o["external_id"] for o in a + b if o["entity_type"] == "Ip"}
    assert ips == {"ip:203.0.113.9"}
    assert all(o["external_id"] != "203.0.113.9" for o in a + b if o["entity_type"] == "Person")
    assert any(lk["relationship"] == "USED_SESSION" for lk in la + lb)
    assert any(lk["relationship"] == "USED_IP" for lk in la + lb)


def test_evaluate_related_object_refs_skips_person():
    mod = _load_payload()
    refs = mod.evaluate_related_object_refs(
        trace_id="tr-a",
        entity_id="guest-aaa",
        event_type="login",
        payload={},
        device_context={"device_id": "dev-same", "signals": {"ip": "203.0.113.9"}},
        session_id="sess-1",
    )
    kinds = {r["entity_type"] for r in refs}
    ids = {r["external_id"] for r in refs}
    assert "Person" not in kinds
    assert "guest-aaa" not in ids
    assert {"Device", "Session", "Ip", "Login"} <= kinds


def test_evaluate_writes_email_and_phone_on_person_not_as_person_id():
    """Investigator finds the Person by email/phone. Email is a clue, not a merge key."""
    mod = _load_payload()
    objects, links = mod.build_evaluate_objects(
        trace_id="tr-mail",
        entity_id="hunt-eval-buyer",
        event_type="login",
        payload={
            "email": "buyer@desk.example",
            "phone": "+15550199",
            "device_id": "hunt-eval-device",
        },
    )
    person = next(o for o in objects if o["entity_type"] == "Person")
    assert person["external_id"] == "hunt-eval-buyer"
    assert person["properties"]["email"] == "buyer@desk.example"
    assert person["properties"]["phone"] == "+15550199"
    assert all(o["external_id"] != "buyer@desk.example" for o in objects if o["entity_type"] == "Person")
    assert all(o["external_id"] != "+15550199" for o in objects if o["entity_type"] == "Person")
    assert any(lk["relationship"] == "USED_DEVICE" for lk in links)


def _link(links, rel, src=None, dst=None):
    for lk in links:
        if lk["relationship"] != rel:
            continue
        if src is not None and lk["from_external_id"] != src:
            continue
        if dst is not None and lk["to_external_id"] != dst:
            continue
        return lk
    return None


def test_login_evaluate_hangs_under_device_not_login():
    """Person > Device > IP; this login evaluate sits under Device."""
    mod = _load_payload()
    objects, links = mod.build_evaluate_objects(
        trace_id="tr-login-h",
        entity_id="buyer-1",
        event_type="login",
        payload={"device_id": "dev-1"},
        device_context={"signals": {"ip": "203.0.113.9"}},
    )
    types = {o["entity_type"]: o["external_id"] for o in objects}
    assert types["Person"] == "buyer-1"
    assert types["Device"] == "dev-1"
    assert types["Ip"] == "ip:203.0.113.9"
    assert types["Login"] == "login:tr-login-h"
    assert _link(links, "USED_IP", src="dev-1", dst="ip:203.0.113.9")
    assert _link(links, "USED_IP", src="buyer-1") is None
    assert _link(links, "RESULTED_IN") is None


def test_payment_evaluate_hangs_under_payment_not_device():
    """Payment had the decision. Device is a sibling. IP hangs under Payment."""
    mod = _load_payload()
    objects, links = mod.build_evaluate_objects(
        trace_id="tr-pay-h",
        entity_id="buyer-1",
        event_type="payment",
        payload={"device_id": "dev-1", "payment_id": "pay-9", "amount": 40},
        device_context={"signals": {"ip": "198.51.100.4"}},
    )
    assert _link(links, "MADE_PAYMENT", src="buyer-1", dst="pay-9")
    assert _link(links, "USED_DEVICE", src="buyer-1", dst="dev-1")
    assert _link(links, "USED_IP", src="pay-9", dst="ip:198.51.100.4")
    assert _link(links, "USED_IP", src="buyer-1") is None
    assert _link(links, "RESULTED_IN") is None


def test_document_and_plate_are_mid_tier_and_own_their_evaluate():
    """Person > Document | LicensePlate > IP. Custom/KYC evaluate hangs under Document even if a device is present."""
    mod = _load_payload()
    objects, links = mod.build_evaluate_objects(
        trace_id="tr-doc",
        entity_id="buyer-1",
        event_type="custom",
        payload={"document_id": "dl-9988", "license_plate": "ABC-1234", "device_id": "dev-kyc"},
        device_context={"device_id": "dev-kyc", "signals": {"ip": "192.0.2.10"}},
    )
    types = {o["entity_type"]: o["external_id"] for o in objects}
    assert types["Document"] == "dl-9988"
    assert types["LicensePlate"] == "plate:ABC-1234"
    assert types["Device"] == "dev-kyc"
    assert _link(links, "USED", src="buyer-1", dst="dl-9988")
    assert _link(links, "USED", src="buyer-1", dst="plate:ABC-1234")
    assert _link(links, "USED_IP", src="dl-9988", dst="ip:192.0.2.10")
    assert _link(links, "RESULTED_IN") is None


def test_ip_only_evaluate_hangs_under_ip():
    mod = _load_payload()
    _objects, links = mod.build_evaluate_objects(
        trace_id="tr-ip",
        entity_id="buyer-1",
        event_type="login",
        payload={},
        device_context={"signals": {"ip": "203.0.113.9"}},
    )
    assert _link(links, "RESULTED_IN") is None
    assert _link(links, "USED_IP", src="buyer-1", dst="ip:203.0.113.9")


def test_blank_entity_id_writes_no_objects():
    mod = _load_payload()
    objects, links = mod.build_evaluate_objects(
        trace_id="tr-x",
        entity_id="  ",
        event_type="payment",
        payload={"device_id": "dev-9"},
    )
    assert objects == []
    assert links == []


def test_build_human_disposition_payload_edges():
    mod = _load_payload()
    payload = mod.build_human_disposition_payload(
        tenant_id="t1",
        case_id="case-1",
        entity_id="acct-1",
        trace_id="tr-1",
        status="escalated",
        actor_id="analyst-1",
        reason_code="ring_evidence",
        prior_decision_id="dec-parent",
    )
    assert payload["kind"] == "human_disposition"
    assert payload["edges"][0]["from_external_id"] == "dec-parent"
    assert payload["edges"][0]["relationship"] == "CAUSED"
    persons = [o["external_id"] for o in payload["objects"] if o["entity_type"] == "Person"]
    assert persons == ["acct-1"]
    assert any(lk["relationship"] == "ACTED_ON" and lk["from_external_id"] == "acct-1" for lk in payload["object_links"])


def test_agent_advise_payload_has_tenant_and_not_observe_shadow():
    """Advise rows carry tenant_id; snapshot.shadow is Observe evaluate only."""
    mod = _load_payload()
    payload = mod.build_agent_advise_payload(
        tenant_id="tenant_alpha",
        run_id="run-1",
        case_id="case-1",
        entity_ids=["acct-1"],
        trace_ids=["tr-1"],
        claims=[{"claim": "escalate"}],
        context_snapshot={},
        source="investigation",
    )
    assert payload["kind"] == "agent_advise"
    assert payload["tenant_id"] == "tenant_alpha"
    assert payload.get("shadow") is not True
    assert "shadow" not in payload
