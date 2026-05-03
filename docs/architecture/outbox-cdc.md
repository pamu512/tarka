# Integration outbox (CDC-style)

Tarka persists domain events to Postgres table `integration_outbox` in the same transaction as
authoritative writes (e.g. `decision_audit` rows, rule reloads, RTBF anonymization). Downstream
relays (Debezium, `pg_notify`, or a lightweight poller) can publish these rows to NATS / Kafka /
ClickHouse without dual-write races.

- **Emission points (initial):** `decision.evaluated`, `config.rule_reload`, `privacy.rtbf_anonymization`
- **Relay contract:** treat `published_at IS NULL` as pending; set `published_at` after successful publish.

See `services/decision-api/alembic/versions/20260503_002_integration_outbox.py` and `IntegrationOutbox` model.
