"""Orchestrator-local analytics helpers (DuckDB, HIL context, providers).

Formerly imported as top-level ``analytics.*``, which collided with the OLAP
package at ``services/analytics`` (``tarka-analytics``).

Public OLAP imports remain ``analytics.engine``, ``analytics.queries``, etc.
Orchestrator code must use ``orchestrator_analytics.*``.

Removal gate: after one release, delete any residual docs that still mention
``services/orchestrator/analytics`` (rg -n 'orchestrator/analytics').
"""
