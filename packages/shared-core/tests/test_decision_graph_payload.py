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
    assert types == {"Person", "Device", "Payment", "Decision"}
    rels = {lk["relationship"] for lk in payload["object_links"]}
    assert "USED_DEVICE" in rels
    assert "MADE_PAYMENT" in rels
    assert "RESULTED_IN" in rels
    assert "BASED_ON" in rels
    assert _link(payload["object_links"], "RESULTED_IN", src="acct-1", dst="dec:tr-1")
    assert _link(payload["object_links"], "BASED_ON", src="dec:tr-1", dst="pay:tr-1")
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


def test_build_evaluate_objects_writes_place_seen_at():
    mod = _load_payload()
    objects, links = mod.build_evaluate_objects(
        trace_id="tr-geo",
        entity_id="buyer-demo",
        event_type="login",
        payload={"session_last_lat": 1.2349, "session_last_lon": 3.4561},
        device_context={"device_id": "dev-1"},
    )
    types = {o["entity_type"]: o["external_id"] for o in objects}
    assert types["Place"] == "cell:3:1.235:3.456"
    assert any(
        lk["relationship"] == "SEEN_AT" and lk["to_external_id"] == types["Place"] for lk in links
    )


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
    assert all(
        o["external_id"] != "buyer@desk.example" for o in objects if o["entity_type"] == "Person"
    )
    assert all(o["external_id"] != "+15550199" for o in objects if o["entity_type"] == "Person")
    assert any(lk["relationship"] == "USED_DEVICE" for lk in links)
    email = next(o for o in objects if o["entity_type"] == "Email")
    phone = next(o for o in objects if o["entity_type"] == "Phone")
    assert email["external_id"] == "email:buyer@desk.example"
    assert phone["external_id"] == "phone:+15550199"
    assert _link(links, "HAS_EMAIL", src="hunt-eval-buyer", dst="email:buyer@desk.example")
    assert _link(links, "HAS_PHONE", src="hunt-eval-buyer", dst="phone:+15550199")


def test_queryable_ids_are_shared_instruments_not_person_merge():
    """ATO / sold account: two Persons, same mailbox / phone / doc / card / address."""
    mod = _load_payload()
    payload = {
        "email": "Sold@X.com",
        "phone": "+15550199",
        "document_id": "passport-9",
        "card_id": "cardtok-1",
        "address": "12 Oak St",
    }
    a, la = mod.build_evaluate_objects(
        trace_id="tr-a", entity_id="acct-old", event_type="login", payload=payload
    )
    b, lb = mod.build_evaluate_objects(
        trace_id="tr-b", entity_id="acct-new", event_type="login", payload=payload
    )
    persons = {o["external_id"] for o in a + b if o["entity_type"] == "Person"}
    assert persons == {"acct-old", "acct-new"}
    assert {o["external_id"] for o in a + b if o["entity_type"] == "Email"} == {
        "email:sold@x.com"
    }
    assert {o["external_id"] for o in a + b if o["entity_type"] == "Phone"} == {
        "phone:+15550199"
    }
    assert {o["external_id"] for o in a + b if o["entity_type"] == "Document"} == {"passport-9"}
    assert {o["external_id"] for o in a + b if o["entity_type"] == "Card"} == {"card:cardtok-1"}
    assert {o["external_id"] for o in a + b if o["entity_type"] == "Address"} == {
        "addr:12 oak st"
    }
    assert _link(la, "HAS_EMAIL", src="acct-old", dst="email:sold@x.com")
    assert _link(lb, "HAS_EMAIL", src="acct-new", dst="email:sold@x.com")
    assert _link(la, "HAS_PHONE", src="acct-old", dst="phone:+15550199")
    assert _link(la, "HAS_CARD", src="acct-old", dst="card:cardtok-1")
    assert _link(lb, "HAS_CARD", src="acct-new", dst="card:cardtok-1")


def test_email_change_writes_new_mailbox_keeps_person():
    """Old mailbox stays a vertex on the first write; later evaluate MERGEs a new Email."""
    mod = _load_payload()
    first, _ = mod.build_evaluate_objects(
        trace_id="tr-1",
        entity_id="acct-1",
        event_type="login",
        payload={"email": "old@x.com"},
    )
    second, _ = mod.build_evaluate_objects(
        trace_id="tr-2",
        entity_id="acct-1",
        event_type="login",
        payload={"email": "new@x.com"},
    )
    emails = {o["external_id"] for o in first + second if o["entity_type"] == "Email"}
    assert emails == {"email:old@x.com", "email:new@x.com"}
    person = next(o for o in second if o["entity_type"] == "Person")
    assert person["properties"]["email"] == "new@x.com"


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
    assert payload["objects"][0]["properties"]["last_act"] == "escalated"
    types = {o["entity_type"] for o in payload["objects"]}
    assert "Decision" in types
    assert _link(payload["object_links"], "RESULTED_IN", src="acct-1")
    assert _link(payload["object_links"], "SUPERSEDES", dst="dec-parent")


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


def test_evaluate_payload_stamps_source_and_desk_markings():
    mod = _load_payload()
    payload = mod.build_evaluate_payload(
        tenant_id="t1",
        trace_id="tr-disp",
        entity_id="acct-1",
        event_type="payment",
        decision="deny",
        score=0.9,
        rule_hits=[],
        fallback_reason=None,
        payload={"payment_id": "pay-1"},
        metadata={"decision_source": "dispute"},
        decision_log_record=None,
        shadow_request=False,
    )
    dec = next(o for o in payload["objects"] if o["entity_type"] == "Decision")
    assert dec["properties"]["source"] == "dispute"
    assert dec["properties"]["markings"] == ["desk"]


def test_empty_markings_stay_hidden():
    """None → desk default. Explicit empty list stays empty (Hunt hides it)."""
    mod = _load_payload()
    assert mod.normalize_markings(None) == ["desk"]
    assert mod.normalize_markings([]) == []
    payload = mod.build_evaluate_payload(
        tenant_id="t1",
        trace_id="tr-hidden",
        entity_id="acct-1",
        event_type="payment",
        decision="deny",
        score=0.9,
        rule_hits=[],
        fallback_reason=None,
        payload={"payment_id": "pay-1"},
        metadata={"markings": []},
        decision_log_record=None,
        shadow_request=False,
    )
    dec = next(o for o in payload["objects"] if o["entity_type"] == "Decision")
    assert dec["properties"]["markings"] == []


def test_allow_decision_ids_over_cap_keeps_material_and_newest_allows():
    mod = _load_payload()
    nodes = [
        {
            "id": f"dec:allow-{i}",
            "labels": ["Decision"],
            "properties": {
                "source": "evaluate",
                "outcome": "allow",
                "kind": "evaluate",
                "created_at": f"2026-08-31T00:{i:02d}:00Z",
            },
        }
        for i in range(21)
    ]
    nodes.append(
        {
            "id": "dec:deny-1",
            "labels": ["Decision"],
            "properties": {
                "source": "evaluate",
                "outcome": "deny",
                "kind": "evaluate",
                "created_at": "2026-08-01T00:00:00Z",
            },
        }
    )
    drop = mod.allow_decision_ids_over_cap(nodes)
    assert drop == ["dec:allow-0"]
    assert "dec:deny-1" not in drop
