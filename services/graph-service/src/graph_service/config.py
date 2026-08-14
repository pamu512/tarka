from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Backend selection (operators flip GRAPH_BACKEND; HTTP API unchanged) ---
    graph_backend: Literal["neo4j", "janusgraph", "age"] = Field(
        default="janusgraph",
        description="Graph persistence: neo4j (Bolt/Cypher), janusgraph (Gremlin), or age (Apache AGE on Postgres).",
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
        description="Max vertices loaded into memory for JanusGraph analytics and search fallback when vertexSearch is not ENABLED.",
    )

    # Optional GNN beta endpoint (non-blocking; heuristics remain source of truth).
    graph_gnn_beta_url: str = Field(
        default="", description="Optional HTTP endpoint for experimental graph risk scoring."
    )
    graph_gnn_beta_timeout_seconds: float = Field(default=0.6, ge=0.1, le=5.0)

    database_url: str = Field(
        default="postgresql://fraud:fraud@postgres:5432/fraud",
        description="Postgres DSN for Apache AGE (asyncpg; use postgresql:// not +asyncpg).",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _asyncpg_dsn(cls, value: object) -> object:
        if isinstance(value, str):
            return value.replace("postgresql+asyncpg://", "postgresql://", 1)
        return value


settings = Settings()
