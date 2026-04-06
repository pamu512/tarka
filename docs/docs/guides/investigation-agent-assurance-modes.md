# Investigation Copilot — assurance modes (operational guide)

This guide describes **optional** controls that make the OSS copilot **more conservative**. None of this is legal or regulatory certification; it reduces *some* classes of silent failure and gives analysts **server-derived** facts separate from model prose.

## Policy knobs (environment)

| Variable | Values | Effect |
|----------|--------|--------|
| `COPILOT_ASSURANCE_MODE` | `standard` (default), `strict` | **strict** withholds the model’s investigative summary when (1) tools returned errors that are not acknowledged in prose, or (2) any claim marked `source=tool` fails deterministic token overlap with successful tool JSON. The API still returns `tool_calls`, `source_refs`, and (in strict) `derived_facts` so the analyst can inspect raw outcomes. |
| `COPILOT_DERIVED_FACTS` | `false` (default), `true` | Adds `derived_facts` to each chat response: scalars **extracted by the server** from successful tool payloads (e.g. `case_id`, `status`, `row_count`). **strict** mode enables this automatically. |
| `COPILOT_INCLUDE_PLATFORM_AUDIT_IN_PROMPT` | `true` / `false` | Set **false** to keep client-supplied platform audit rows **out** of the system prompt (reduces prompt-injection supply chain from the UI). Analyst context from audit is then absent unless you add it another way. |
| `COPILOT_INJECTION_POLICY` | `sanitize`, `reject` | **reject** blocks the request when injection-like patterns are detected (no tools run). |

## Human sign-off (workflow hook)

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/review/turn` | Body: `turn_id`, `tenant_id`, `analyst_id`, `status` (`approved` \| `rejected`), optional `note`. Persists to SQLite (`COPILOT_REVIEW_DB_NAME` under `INVESTIGATION_DATA_DIR`). |
| `GET /v1/review/turn?turn_id=&tenant_id=` | Latest review row for that turn, if any. |

The UI or a case workflow can require **approved** before exporting labels or attaching copilot output to a case record. Enforcement is **your** orchestration layer; the agent only stores the record.

## Evaluation harness (CI / local)

Run the focused tests:

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared pytest tests/test_assurance_mode.py -q
```

These cover derived-fact extraction, strict violation detection, and review persistence—not end-to-end LLM behavior.

## Positioning (honest)

- **Strict** mode is a **refusal** strategy, not proof of correctness: the model might still have been right while failing heuristics, or wrong while passing them.
- **Derived facts** are only as trustworthy as the **tools** and **upstream APIs**; they do not validate business truth.
- Combine with existing features: **maker–checker** for sensitive tools (`COPILOT_REVIEWER_SECRET`), **judge pass** for an extra LLM audit (cost/latency), and **feedback** analytics for quality loops.

See also: [investigation-agent-intended-use-and-data-flows.md](investigation-agent-intended-use-and-data-flows.md), [investigation-agent-llm-data-flow.md](investigation-agent-llm-data-flow.md), [investigation-agent-project.md](../projects/investigation-agent-project.md).
