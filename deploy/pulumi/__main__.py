"""Tarka Triple-DB Pulumi program (Python runtime).

Configuration is read from stack config (see ``Pulumi.dev.yaml`` for local defaults).
Exports include host/port fields plus FastAPI-ready connection strings:

- ``fastapiDatabaseUrl``, ``fastapiRedisUrl``, ``tripleDbDotenv`` (all secrets — use
  ``pulumi stack output <name> --show-secrets``). Write a local fragment with::

    pulumi stack output tripleDbDotenv --show-secrets > .env.triple-db

  Do not commit files produced with ``--show-secrets``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pulumi

# ``deploy/postgres.py`` lives next to this package (``deploy/pulumi``).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import clickhouse as clickhouse_stack  # noqa: E402
import engine_signing  # noqa: E402
import fastapi_env  # noqa: E402
import postgres  # noqa: E402
import redis as redis_stack  # noqa: E402

cfg = pulumi.Config()

pulumi.export("environment", cfg.get("environment") or "dev")
pulumi.export("postgresHost", cfg.require("postgresHost"))
pulumi.export("postgresPort", int(cfg.require("postgresPort")))
pulumi.export("postgresDatabase", cfg.require("postgresDatabase"))
pulumi.export("clickhouseHost", cfg.require("clickhouseHost"))
pulumi.export("clickhouseHttpPort", int(cfg.require("clickhouseHttpPort")))
pulumi.export("clickhouseNativePort", int(cfg.require("clickhouseNativePort")))
pulumi.export("clickhouseDatabase", cfg.require("clickhouseDatabase"))
pulumi.export("redisHost", cfg.require("redisHost"))
pulumi.export("redisPort", int(cfg.require("redisPort")))
pulumi.export("redisDb", int(cfg.require("redisDb")))

postgres.provision(cfg=cfg)
redis_stack.provision(cfg=cfg)
clickhouse_stack.provision(cfg=cfg)
engine_signing.provision(cfg=cfg)
fastapi_env.export_fastapi_triple_db_outputs(cfg=cfg)
