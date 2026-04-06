# Minimal upstream mock (Case + Graph + Decision shapes)

Lightweight HTTP server with **stdlib only** so you can point **investigation-agent** at fake upstreams for **adapter development** or smoke tests without running the full Tarka stack.

## Run

```bash
# Terminal A — mock listens on 18080 (case+decision+graph paths on one port for local demos)
python scripts/integration_adapter_mock/server.py --port 18080

# Terminal B — agent (example: all three URLs point at mock; adjust ports if you split)
export CASE_API_URL=http://127.0.0.1:18080
export DECISION_API_URL=http://127.0.0.1:18080
export GRAPH_SERVICE_URL=http://127.0.0.1:18080
# … start investigation-agent …
```

Then:

```bash
python scripts/ci/check_integration_contract.py --base-url http://localhost:8006
```

## Limits

- Responses are **stub JSON** (empty queues, empty graph, minimal audit). Enough for **connectivity** and **tool loop** experiments, not realistic fraud data.
- **Not** a substitute for contract tests against real services.

## Related

- [Investigation Copilot — integration contract](../../docs/docs/guides/investigation-agent-integration-contract.md)
- [CHANGELOG_INTEGRATION](../../docs/docs/guides/CHANGELOG_INTEGRATION.md)
