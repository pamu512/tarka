"""Graph signal math uses graph_contract tokens."""

from datetime import UTC, datetime

from graph_signals import SignalHop, compute_graph_signals


def test_two_hop_cards_use_contract_tokens() -> None:
    now = datetime(2026, 11, 17, tzinfo=UTC)
    hops = [
        SignalHop(
            src_label="user",
            src_id="u1",
            rel="USED_IP",
            dst_label="ip",
            dst_id="203.0.113.9",
            observed_at=now,
        ),
        SignalHop(
            src_label="user",
            src_id="u2",
            rel="USED_IP",
            dst_label="ip",
            dst_id="203.0.113.9",
            observed_at=now,
        ),
        SignalHop(
            src_label="user",
            src_id="u2",
            rel="MADE_PAYMENT",
            dst_label="payment",
            dst_id="card-9",
            observed_at=now,
        ),
    ]
    out = compute_graph_signals("user", "u1", hops, now=now)
    assert out["two_hop_distinct_cards_last_2h"] == 1
