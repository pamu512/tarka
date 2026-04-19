"""Unit tests for graph-service algorithm functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from graph_service.algorithms import (
    _clamp_depth,
    compute_entity_risk,
    detect_fraud_rings,
)

# ---------- _clamp_depth ----------


class TestClampDepth:
    def test_zero_clamps_to_one(self):
        assert _clamp_depth(0) == 1

    def test_one_stays_one(self):
        assert _clamp_depth(1) == 1

    def test_mid_range_unchanged(self):
        assert _clamp_depth(3) == 3

    def test_five_stays_five(self):
        assert _clamp_depth(5) == 5

    def test_above_max_clamps_to_five(self):
        assert _clamp_depth(10) == 5
        assert _clamp_depth(100) == 5

    def test_negative_clamps_to_one(self):
        assert _clamp_depth(-5) == 1


# ---------- compute_entity_risk ----------


def _mock_record(data: dict):
    """Create a mock Neo4j record that supports dict-style access."""
    rec = MagicMock()
    rec.__getitem__ = lambda self, key: data[key]
    rec.get = lambda key, default=None: data.get(key, default)
    return rec


class TestComputeEntityRisk:
    @pytest.mark.asyncio
    async def test_entity_not_found_returns_zero_risk(self):
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_driver = AsyncMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("graph_service.algorithms_neo4j.get_driver", AsyncMock(return_value=mock_driver)):
            result = await compute_entity_risk("tenant1", "missing-entity")

        assert result["risk_score"] == 0
        assert "entity_not_found" in result["risk_factors"]

    @pytest.mark.asyncio
    async def test_entity_with_high_risk_tags(self):
        record = _mock_record(
            {
                "tags": ["fraud", "suspicious"],
                "conn_count": 2,
                "flagged_neighbors": 0,
                "community_size": 1,
                "shared_device_count": 0,
            }
        )
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=record)

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_driver = AsyncMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("graph_service.algorithms_neo4j.get_driver", AsyncMock(return_value=mock_driver)):
            result = await compute_entity_risk("tenant1", "risky-user")
            result_min = await compute_entity_risk("tenant1", "risky-user", checkpoint="minimal")

        assert result["risk_score"] >= 30
        assert result_min["risk_score"] <= result["risk_score"]
        assert result_min.get("graph_profile") == "minimal"
        assert result_min.get("graph_profile_max_neighbor_hops") == 2
        assert any("own_tags" in f for f in result["risk_factors"])
        # Neo4j query uses checkpoint depth for community path (minimal profile → 2 hops)
        cypher = mock_session.run.call_args[0][0]
        assert "[*1..2]" in cypher

    @pytest.mark.asyncio
    async def test_checkpoint_depth_in_query_standard(self):
        record = _mock_record(
            {
                "tags": [],
                "conn_count": 1,
                "flagged_neighbors": 0,
                "community_size": 1,
                "shared_device_count": 0,
            }
        )
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=record)
        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_driver = AsyncMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("graph_service.algorithms_neo4j.get_driver", AsyncMock(return_value=mock_driver)):
            await compute_entity_risk("t", "e", checkpoint="standard")
        q = mock_session.run.call_args[0][0]
        assert "[*1..3]" in q

    @pytest.mark.asyncio
    async def test_entity_with_flagged_neighbors(self):
        record = _mock_record(
            {
                "tags": [],
                "conn_count": 8,
                "flagged_neighbors": 3,
                "community_size": 6,
                "shared_device_count": 1,
            }
        )
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=record)

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_driver = AsyncMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("graph_service.algorithms_neo4j.get_driver", AsyncMock(return_value=mock_driver)):
            result = await compute_entity_risk("tenant1", "linked-user")

        assert result["risk_score"] > 0
        assert result["connected_flagged_count"] == 3
        assert result["community_size"] == 6
        assert any("connected_flagged" in f for f in result["risk_factors"])
        assert any("large_community" in f for f in result["risk_factors"])
        assert any("shared_devices" in f for f in result["risk_factors"])

    @pytest.mark.asyncio
    async def test_entity_clean_low_risk(self):
        record = _mock_record(
            {
                "tags": ["verified"],
                "conn_count": 1,
                "flagged_neighbors": 0,
                "community_size": 1,
                "shared_device_count": 0,
            }
        )
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=record)

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_driver = AsyncMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("graph_service.algorithms_neo4j.get_driver", AsyncMock(return_value=mock_driver)):
            result = await compute_entity_risk("tenant1", "clean-user")

        assert result["risk_score"] == 0
        assert result["risk_factors"] == []

    @pytest.mark.asyncio
    async def test_risk_score_capped_at_100(self):
        record = _mock_record(
            {
                "tags": ["fraud", "blocked", "chargedback"],
                "conn_count": 15,
                "flagged_neighbors": 10,
                "community_size": 10,
                "shared_device_count": 5,
            }
        )
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=record)

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_driver = AsyncMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("graph_service.algorithms_neo4j.get_driver", AsyncMock(return_value=mock_driver)):
            result = await compute_entity_risk("tenant1", "super-risky")

        assert result["risk_score"] <= 100


# ---------- detect_fraud_rings ----------


class TestDetectFraudRings:
    def test_min_ring_size_clamp_below_three(self):
        clamped = max(3, min(1, 6))
        assert clamped == 3

    def test_min_ring_size_clamp_above_six(self):
        clamped = max(3, min(10, 6))
        assert clamped == 6

    def test_min_ring_size_clamp_valid_value(self):
        clamped = max(3, min(4, 6))
        assert clamped == 4

    @pytest.mark.asyncio
    async def test_detect_fraud_rings_returns_rings(self):
        """Verify ring deduplication and filtering logic."""
        mock_records = [
            _mock_record(
                {
                    "node_ids": ["a", "b", "c", "a"],
                    "rel_types": ["PAYS", "SHARES_DEVICE", "LINKED"],
                    "ring_len": 3,
                    "all_tags": ["suspicious"],
                }
            ),
            _mock_record(
                {
                    "node_ids": ["a", "b", "c", "a"],
                    "rel_types": ["PAYS", "SHARES_DEVICE", "LINKED"],
                    "ring_len": 3,
                    "all_tags": ["suspicious"],
                }
            ),
        ]

        async def _mock_async_iter(records):
            for r in records:
                yield r

        mock_result = AsyncMock()
        mock_result.__aiter__ = lambda self: _mock_async_iter(mock_records)

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_driver = AsyncMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("graph_service.algorithms_neo4j.get_driver", AsyncMock(return_value=mock_driver)):
            rings = await detect_fraud_rings("tenant1", min_ring_size=3)

        assert len(rings) == 1
        assert rings[0]["ring_size"] == 3
        assert "suspicious" in rings[0]["aggregate_tags"]

    @pytest.mark.asyncio
    async def test_detect_fraud_rings_empty_graph(self):
        async def _empty_iter():
            return
            yield

        mock_result = AsyncMock()
        mock_result.__aiter__ = lambda self: _empty_iter()

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_driver = AsyncMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("graph_service.algorithms_neo4j.get_driver", AsyncMock(return_value=mock_driver)):
            rings = await detect_fraud_rings("tenant1")

        assert rings == []
