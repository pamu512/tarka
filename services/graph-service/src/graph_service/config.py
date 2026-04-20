from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Backend selection (operators flip GRAPH_BACKEND; HTTP API unchanged) ---
    graph_backend: Literal["neo4j", "janusgraph"] = Field(
        default="neo4j",
        description="Graph persistence: neo4j (Bolt/Cypher) or janusgraph (Gremlin Server).",
    )

    # --- Neo4j (default) ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # --- JanusGraph / Gremlin Server ---
    janusgraph_gremlin_url: str = Field(
        default="ws://localhost:8182/gremlin",
        description="WebSocket URL to Gremlin Server (JanusGraph remote).",
    )
    janusgraph_traversal_source: str = Field(
        default="g",
        description="Traversal source name bound on the server (usually 'g').",
    )
    janusgraph_analytics_vertex_cap: int = Field(
        default=8000,
        ge=100,
        le=500_000,
        description="Max vertices loaded into memory for JanusGraph analytics fallbacks.",
    )

    # Optional GNN beta endpoint (non-blocking; heuristics remain source of truth).
    graph_gnn_beta_url: str = Field(default="", description="Optional HTTP endpoint for experimental graph risk scoring.")
    graph_gnn_beta_timeout_seconds: float = Field(default=0.6, ge=0.1, le=5.0)


settings = Settings()
