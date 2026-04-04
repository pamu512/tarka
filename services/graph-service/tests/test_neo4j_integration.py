"""Live Neo4j smoke test — enabled when NEO4J_INTEGRATION=1 (CI service container)."""
import os

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def neo4j_config():
    if os.environ.get("NEO4J_INTEGRATION") != "1":
        pytest.skip("NEO4J_INTEGRATION not enabled")
    return {
        "uri": os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
        "user": os.environ.get("NEO4J_USER", "neo4j"),
        "password": os.environ.get("NEO4J_PASSWORD", "neo4j"),
    }


async def test_neo4j_driver_return_one(neo4j_config: dict):
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(
        neo4j_config["uri"],
        auth=(neo4j_config["user"], neo4j_config["password"]),
    )
    try:
        async with driver.session() as session:
            result = await session.run("RETURN 1 AS n")
            record = await result.single()
            assert record is not None
            assert record["n"] == 1
    finally:
        await driver.close()
