from __future__ import annotations
import hashlib
import re

"""Built-in investigation playbooks — structured workflow hints appended to the copilot system prompt.

These reduce the \"empty canvas\" weakness vs suite vendors by shipping opinionated checklists.
They do not auto-execute tools; the model still must call tools. Playbooks are advisory templates.

Workflow themes draw on public scheme/program descriptions (e.g. Visa acquirer monitoring-style fraud+dispute
ratios and enumeration, Mastercard chargeback/dispute program concepts, MRC-style fraud-ops practice) and
common industry typologies. They are **not** legal or scheme-compliance advice; analysts must follow your
network rules and counsel.
"""
_PLAYBOOK_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$", re.IGNORECASE)

# id -> { title, vertical, fragment }
_PLAYBOOKS: dict[str, dict[str, str]] = {
    "payments_first_party": {
        "title": "Payments — first-party / friendly fraud",
        "vertical": "payments",
        "fragment": (
            "\n\nACTIVE PLAYBOOK — Payments (first-party / friendly fraud):\n"
            "Follow this order unless the analyst overrides; cite tools for each factual statement.\n"
            "1) **Case + decision**: get_case or list_cases; get_decision_audit(trace_id) for inference_context, "
            "drivers, velocity slice, recommended_action.\n"
            "2) **Identity & history**: subgraph_with_velocity on entity_id; compare device/SDK signals "
            "(VPN, emulator, automation) vs narrative.\n"
            "3) **Disputes / chargebacks**: if case links disputes, reason codes and outcomes matter — "
            "use case payload or list patterns; do not invent chargeback data.\n"
            "4) **Batch cohort** (if batch_id in session): aggregate_batch_column on amount-like columns; "
            "query_batch_rows for outliers linked to entity_id/trace_id columns.\n"
            "5) **Advisory close**: separate verified tool facts from hypotheses; flag governance review if "
            "policy-sensitive attributes appear.\n"
        ),
    },
    "account_takeover": {
        "title": "Account takeover (ATO)",
        "vertical": "fintech",
        "fragment": (
            "\n\nACTIVE PLAYBOOK — Account takeover (ATO):\n"
            "1) **Decision audit**: get_decision_audit — tamper/replay/network_trust/geo-consistency, "
            "top_signals, tier.\n"
            "2) **Graph**: subgraph_with_velocity — new devices, shared devices across entities, "
            "velocity on login/account nodes.\n"
            "3) **Velocity**: get_entity_velocity for burst patterns vs baseline.\n"
            '4) **Session vs fraud narrative**: reconcile "new device + new geo" with customer history '
            "only from tool outputs.\n"
            "5) **Containment ideas** (advisory): step-up, session revoke, password reset — state as "
            "recommendations, not executed actions.\n"
        ),
    },
    "refund_promo_abuse": {
        "title": "Refund & promo abuse",
        "vertical": "ecommerce_food_delivery",
        "fragment": (
            "\n\nACTIVE PLAYBOOK — Refund / promo / goodwill abuse:\n"
            "1) **Entity graph**: subgraph_with_velocity — linked accounts, shared payment instruments, "
            "addresses, devices.\n"
            "2) **Velocity**: order/refund counts per entity from decision audit + velocity if present.\n"
            "3) **Batch** (if batch_id): value_counts on SKU, merchant, promo_code, refund_reason columns; "
            "numeric_summary on amounts.\n"
            "4) **Pattern language**: describe repeat refunders, timing clusters, and collusion hypotheses "
            "only when tools support; avoid stereotype proxies.\n"
        ),
    },
    "mule_layering": {
        "title": "Money mule & layering indicators",
        "vertical": "payments_fincrime",
        "fragment": (
            "\n\nACTIVE PLAYBOOK — Mule / layering (indicators only):\n"
            "1) **Graph depth 2–3**: subgraph_with_velocity — fan-in/fan-out, rapid funds movement paths.\n"
            "2) **Velocity + tags**: get_entity_tags and velocity; correlate spikes with rule_hits in audit.\n"
            "3) **Weak labels**: export_outcome_labeled_dataset or get_stored_labeled_dataset for prior "
            "analyst/dispute signals — noisy, label explicitly.\n"
            "4) **SAR-style**: outline facts vs suspicion using tool-backed bullets; never assert criminality; "
            "human disposition required.\n"
        ),
    },
    "scheme_monitoring_merchant": {
        "title": "Scheme-style monitoring (fraud + disputes + testing)",
        "vertical": "payments_acquiring",
        "fragment": (
            "\n\nACTIVE PLAYBOOK — Scheme-style merchant/acquirer exposure (investigation framing):\n"
            "Use when risk looks like **unified fraud+dispute pressure** or **card testing/enumeration** "
            "(public analogs: acquirer monitoring that blends fraud chargebacks and non-fraud disputes, "
            "plus high decline/validation-attempt rates). This is **not** a compliance determination.\n"
            "1) **Segment**: list_cases / batch — split populations by fraud-labeled vs service/credit "
            "dispute outcomes, channel, MID, product line **only if fields exist in tools**.\n"
            "2) **Enumeration / testing proxy**: velocity on auth attempts, declines, or low-value "
            "probes from decision audit + get_entity_velocity; flag burst clusters and shared devices/BINs "
            "via subgraph_with_velocity.\n"
            "3) **Dispute linkage**: tie entities to dispute/case records when present; reason-code or "
            "category fields — never invent codes.\n"
            "4) **Controls narrative (advisory)**: pre-dispute resolution, stronger CNP controls, device "
            "and velocity rules — frame as hypotheses tied to observed signals.\n"
            "5) **Close**: metrics the risk owner should track (ratios, numerators/denominators) as "
            "**questions**, not certainties.\n"
        ),
    },
    "disputes_chargebacks": {
        "title": "Disputes & chargebacks (lifecycle + evidence)",
        "vertical": "payments_disputes",
        "fragment": (
            "\n\nACTIVE PLAYBOOK — Disputes / chargebacks (Mastercard/Visa-style lifecycle thinking):\n"
            "1) **Triage by dispute family** (fraud vs processing vs consumer dispute) using **only** "
            "case/dispute/decision fields returned by tools — map to issuer narrative vs merchant facts.\n"
            "2) **Authorization & processing**: get_decision_audit — AVS/CVV/3DS outcomes, auth timestamps, "
            "duplicate processing indicators if present.\n"
            "3) **Fulfillment & digital goods**: delivery/usage/IP/device correlation **only from tool data**; "
            "do not fabricate tracking or receipts.\n"
            "4) **Representment / second presentment mindset**: list evidence gaps (what would strengthen "
            "the file) as bullet questions for ops — not legal advice.\n"
            "5) **Graph**: shared payment methods or devices across disputing and non-disputing entities "
            "when disputes suggest collusion or organized abuse.\n"
        ),
    },
    "aml_escalation": {
        "title": "AML & fincrime escalation (facts vs suspicion)",
        "vertical": "aml_fincrime",
        "fragment": (
            "\n\nACTIVE PLAYBOOK — AML / fincrime escalation (beyond mule indicators):\n"
            "1) **Pattern scan**: velocity and amounts from audits — rapid in-out, round amounts, "
            "structuring-like cadence **only if visible in tools**; no invented thresholds.\n"
            "2) **Counterparties**: subgraph_with_velocity — concentration, shell-like fan-out, "
            "cross-entity flows; label uncertainty.\n"
            "3) **Sanctions/PEP**: mention only if your upstream APIs expose lists or hits in tool output.\n"
            "4) **Narrative prep**: bullet **facts** (tool-backed) vs **suspicion** (hypothesis); "
            "recommend MLRO/Compliance handoff when policy triggers — you do not file or decide.\n"
            "5) **Avoid**: asserting laundering, source of funds, or criminal conduct; use "
            '"indicators" and "warrants review".\n'
        ),
    },
    "collusion_fake_accounts": {
        "title": "Collusion, fake & duplicate accounts",
        "vertical": "platform_abuse",
        "fragment": (
            "\n\nACTIVE PLAYBOOK — Collusion / fake / multi-account abuse:\n"
            "1) **Identity resolution**: subgraph_with_velocity — shared devices, cards, bank accounts, "
            "addresses, referral codes, IP clusters; quantify neighbor overlap.\n"
            "2) **Lifecycle**: account age vs first high-value action; burst registrations from same "
            "device/network (velocity).\n"
            "3) **Incentives**: referral, signup bonus, or promo eligibility abuse — cross-check with "
            "refund_promo or coupon patterns if the case spans both.\n"
            "4) **Organized rings**: community detection or dense subgraph if tools support; describe "
            "coordination only with graph/audit support.\n"
            "5) **Fairness**: avoid demographic proxies; stick to behavioral and instrument link evidence.\n"
        ),
    },
    "coupon_instrument_abuse": {
        "title": "Coupon, stacking & instrument-led promo abuse",
        "vertical": "ecommerce_promo",
        "fragment": (
            "\n\nACTIVE PLAYBOOK — Coupon stuffing, stacking, leaked codes, instrument farming:\n"
            "1) **Batch** (if batch_id): aggregate_batch_column / query_batch_rows on promo_code, "
            "coupon_id, campaign, discount_pct, payment_instrument_hash or last4 if present.\n"
            "2) **Concentration**: single code across many entity_ids; same instrument redeeming many codes; "
            "time-windowed redemption velocity.\n"
            "3) **Graph**: entities linked by shared device, card, address, or pickup location around "
            "redemption spikes.\n"
            "4) **Policy**: single-use vs multi-use code design and stack limits — advisory recommendations "
            "only, tied to observed abuse pattern.\n"
        ),
    },
    "fulfillment_inrb_snad": {
        "title": "Fulfillment — INR, SNAD, damage, theft claims",
        "vertical": "ecommerce_logistics",
        "fragment": (
            "\n\nACTIVE PLAYBOOK — Item not received (INR), not as described (SNAD), damage, theft:\n"
            "1) **Claim vs record**: align dispute/chargeback reason with order, fulfillment, and "
            "carrier timestamps **from tools only**.\n"
            "2) **Customer history**: prior INR/SNAD rate for entity from cases/disputes if available; "
            "decision_audit for repeat high-risk signals.\n"
            "3) **Geo / device**: contrast delivery address, IP, and device history with claim — "
            'no "they lied" without data.\n'
            "4) **Friendly fraud angle**: first-party misuse hypotheses only when velocity, history, "
            "and graph support; separate from organized reshipping rings (use collusion playbook cues).\n"
            "5) **Outcome**: recovery, partial refund, ban, or accept loss — state as business options, "
            "not instructions.\n"
        ),
    },
}


def list_playbooks() -> list[dict[str, str]]:
    return [{"id": k, "title": v["title"], "vertical": v["vertical"]} for k, v in sorted(_PLAYBOOKS.items(), key=lambda x: x[0])]


def playbooks_catalog_fingerprint() -> str:
    """Short stable id over built-in playbook ids + fragment text (adapter/cache hints when playbooks ship)."""
    h = hashlib.sha256()
    for k in sorted(_PLAYBOOKS.keys()):
        h.update(k.encode())
        h.update(b"\0")
        h.update(_PLAYBOOKS[k]["fragment"].encode())
    return h.hexdigest()[:16]


def validate_playbook_id(raw: str | None) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).strip()
    if not _PLAYBOOK_ID_RE.match(s):
        raise ValueError("Invalid playbook_id (use a-z, 0-9, underscore, hyphen; max 64 chars)")
    if s not in _PLAYBOOKS:
        raise ValueError(f"Unknown playbook_id: {s}")
    return s


def playbook_system_append(playbook_id: str) -> str:
    return _PLAYBOOKS[playbook_id]["fragment"]
