import inspect

from graph_service import age_client, janusgraph_gremlin, janusgraph_store, neo4j_client
from graph_service.entity_risk_score import SEARCH_PROP_KEYS, cypher_search_prop_predicate


def test_janus_search_uses_prefix_index_and_batch_hydrate():
    src = inspect.getsource(janusgraph_store.search_entities)
    hydrate = inspect.getsource(janusgraph_store._batch_valuemap)
    gremlin_src = inspect.getsource(janusgraph_gremlin)
    assert "textContainsPrefix" in src
    assert "_batch_valuemap" in src
    assert "valueMap" in hydrate
    assert "both().limit(10)" in src
    assert "vertexSearch" in gremlin_src
    assert "byTenantExternal" in gremlin_src
    assert "Client" in gremlin_src
    assert "submit" in gremlin_src
    assert "truncated" in src
    assert "janusgraph_analytics_vertex_cap" in src
    assert "eligible_search_node_prefix" in src
    assert "elementMap" not in src
    assert 'for v in g.V().has("tenant_id")' not in src
    assert "for v in g.V().has('tenant_id')" not in src


def test_janus_fallback_mentions_cap_and_truncated():
    src = inspect.getsource(janusgraph_store.search_entities)
    assert "limit(" in src
    assert "truncated" in src


def test_cypher_backends_keep_contains():
    nsrc = inspect.getsource(neo4j_client.search_entities)
    asrc = inspect.getsource(age_client.search_entities)
    assert "CONTAINS" in inspect.getsource(cypher_search_prop_predicate)
    assert "textContainsPrefix" not in nsrc
    assert "textContainsPrefix" not in asrc


def test_vertex_search_groovy_covers_allowlist_and_composite():
    src = inspect.getsource(janusgraph_gremlin)
    assert "vertexSearch" in src
    assert "byTenantExternal" in src
    assert "unique" in src
    assert "TEXTSTRING" in src
    assert "'search'" in src or '"search"' in src
    for key in SEARCH_PROP_KEYS:
        assert key in src or "SEARCH_PROP_KEYS" in src


def test_janus_subgraph_one_roundtrip_per_layer():
    sub = inspect.getsource(janusgraph_store._query_subgraph_sync)
    deep = inspect.getsource(janusgraph_store._query_entity_deep_context_sync)
    walk = inspect.getsource(janusgraph_store._walk_incident_layers)
    assert "g.V(v).bothE()" not in sub
    assert "g.V(v).bothE()" not in deep
    assert "bothE().toList()" not in sub
    assert "elementMap" not in sub
    assert "elementMap" not in deep
    assert "valueMap" in walk
    assert "bothE" in walk
    assert "for layer" in walk or "range(" in walk
