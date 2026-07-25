# Analytics namespace (orchestrator)

Orchestrator-local helpers moved to [`orchestrator_analytics/`](orchestrator_analytics/).

Public OLAP package remains `services/analytics` (`import analytics.engine`, …).

A top-level `services/orchestrator/analytics` package was removed on purpose so it
no longer shadows `tarka-analytics` on `PYTHONPATH`.

Removal gate: delete this note once docs no longer mention the old path
(`rg -n 'orchestrator/analytics'`).
