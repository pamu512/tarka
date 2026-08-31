from graph_service.object_attention import score_object_attention


def test_ip_never_clears_pack_bar():
    row = score_object_attention(
        entity_type="Ip",
        person_fanout=400,
        review_or_deny_neighbors=20,
        on_this_event=True,
    )
    assert row["attend_pack"] is False
    assert row["attend_hunt"] is True
    assert row["importance"] < 40


def test_shared_device_without_outcomes_is_hunt_only():
    row = score_object_attention(
        entity_type="Device",
        person_fanout=4,
        review_or_deny_neighbors=0,
        on_this_event=True,
    )
    assert row["attend_pack"] is False
    assert row["attend_hunt"] is True


def test_hot_device_on_this_event_attends_pack():
    row = score_object_attention(
        entity_type="Device",
        person_fanout=4,
        review_or_deny_neighbors=3,
        on_this_event=True,
    )
    assert row["attend_pack"] is True
    assert "pack:hot_outcomes" in row["reasons"]


def test_hot_device_not_on_this_event_does_not_attend_pack():
    row = score_object_attention(
        entity_type="Device",
        person_fanout=4,
        review_or_deny_neighbors=3,
        on_this_event=False,
    )
    assert row["attend_pack"] is False


def test_shared_card_fanout_attends_pack():
    row = score_object_attention(
        entity_type="Payment",
        person_fanout=3,
        review_or_deny_neighbors=0,
        on_this_event=True,
    )
    assert row["attend_pack"] is True
    assert "pack:shared_instrument" in row["reasons"]


def test_stats_count_persons_and_hot_neighbors():
    from graph_service.object_attention import stats_from_subgraph

    fanout, hot = stats_from_subgraph(
        "dev-1",
        [
            {"id": "dev-1", "labels": ["Device"]},
            {"id": "g1", "labels": ["Person"], "risk_score": 80},
            {"id": "g2", "labels": ["Person"], "risk_score": 10},
            {"id": "dec-1", "labels": ["Decision"], "properties": {"outcome": "review"}},
        ],
    )
    assert fanout == 2
    assert hot == 2


def test_payment_ranks_above_ip():
    pay = score_object_attention(
        entity_type="Payment", person_fanout=1, review_or_deny_neighbors=0, on_this_event=False
    )
    ip = score_object_attention(
        entity_type="Ip", person_fanout=80, review_or_deny_neighbors=0, on_this_event=False
    )
    assert pay["importance"] > ip["importance"]
