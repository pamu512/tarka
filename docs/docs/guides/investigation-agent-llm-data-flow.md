# Investigation Copilot — LLM data flow (operators & compliance)

The **investigation-agent** service (`services/investigation-agent`) sends **tenant-scoped investigation context** to a **configurable OpenAI-compatible HTTP API** (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`) for multi-turn chat with **function tools** that call internal APIs only.

## What may leave your boundary

| Data class | Path | Notes |
|------------|------|--------|
| **User / assistant chat text** | Request body → LLM provider | User messages are pattern-sanitized; **assistant history is treated as untrusted** and sanitized the same way before resend. Length caps apply. **`COPILOT_INJECTION_POLICY`**: default `sanitize` (redact patterns and continue, response may include `injection_sanitized`); set `reject` to hard-block on heuristic match (higher false-positive risk on analyst prose). |
| **System prompt** | Built server-side | Includes fraud-investigation rules, optional **normalized + sanitized** platform audit slice when **`COPILOT_INCLUDE_PLATFORM_AUDIT_IN_PROMPT=true`** (default). Set to `false` to drop audit text from the LLM context entirely (client-supplied audit is still a supply-chain surface; length limits and field sanitization reduce but do not remove that class of risk). |
| **Tool definitions** | JSON schema to LLM | Describes tool names and parameters (no live PII in the schema itself). |
| **Tool results** | Returned from Case API, Graph Service, Decision API → JSON in LLM context | Truncated per tool (`_limit_result`) and per message (8k chars per tool result in the conversation). |
| **Structured claims trailer** | Parsed server-side, **stripped from `reply`** | The model is instructed to append `TARKA_CLAIMS_JSON={...}`; the API returns **`claims`** separately with `source` ∈ `tool` \| `unknown`. When **`COPILOT_ENFORCE_TOOL_CLAIM_GROUNDING=true`** (default), `source=tool` claims that do not overlap grounding tokens from **successful** tool calls are **downgraded** to `unknown`; the API may set **`claims_grounding_adjustments`** (machine-oriented reasons). This is a heuristic, not proof that prose is hallucination-free. |

## What does not go to the LLM

- **Raw** cross-tenant data: `tenant_id` and `analyst_id` on the chat request are **server-authoritative**; tool implementations **ignore** any `tenant_id` (or similar) inside model-generated tool arguments and use the session tenant (see tests in `test_agent_security.py`).
- **Secrets**: Output passes through a blocklist redactor; prompts forbid exfil patterns (not a guarantee against a compromised model).

## Subprocessors & contracts

Using a **public cloud LLM** (e.g. default OpenAI API URL) makes that provider a **subprocessor** for any content above. For regulated workloads:

- Prefer **enterprise / VPC / self-hosted** inference with a **DPA** and **data residency** terms.
- Disable or gate **`platform_audit`** if audit rows may contain identifiers or sensitive narratives your policy forbids from leaving the estate (use **`COPILOT_INCLUDE_PLATFORM_AUDIT_IN_PROMPT=false`** to keep the request for logging/UI but omit audit from the model context).
- Set **`ALLOWED_ANALYSTS`** to restrict which analyst IDs may call the copilot.
- Set **`API_KEYS`** and **`COPILOT_REQUIRE_INVESTIGATION_API_KEY=true`** so the agent refuses to start chat without service auth (avoids “empty keys → open endpoint” operator mistakes).
- Optionally set **`COPILOT_DISABLED_TOOLS`** (comma-separated names) to hide powerful tools (e.g. replay, label export) from the model in stricter deployments.
- Cap cost and depth: **`COPILOT_MAX_TOOL_ITERATIONS`**, **`COPILOT_MAX_COMPLETION_TOKENS`** (per completion round toward the LLM).

## Response contract (`POST /v1/chat`)

- **`reply`**: Prose only (claims trailer removed); redacted and length-capped.
- **`tool_calls`**: Tools invoked with args and results (for UI transparency).
- **`claims`**: List of `{ "text", "source" }` with `source` either **`tool`** or **`unknown`** (server-validated). If the model omits or breaks the trailer, the server emits **fallback claims** with `source: unknown` and may set **`claims_warning`**.
- **`claims_grounding_adjustments`**: Present when claim sources were adjusted for tool grounding (see above).
- **`warning`**: `injection_detected` when **`COPILOT_INJECTION_POLICY=reject`** and regex heuristics fire (request not sent to the LLM).
- **`injection_sanitized`**: `true` when heuristics matched under **`COPILOT_INJECTION_POLICY=sanitize`** (default); the request continued after redaction.

## Related docs

- **Intended use, out of scope, full data-flow map (RAG, feedback, review, regional builds):** [investigation-agent-intended-use-and-data-flows.md](./investigation-agent-intended-use-and-data-flows.md)
- **Integration contract (`GET /v1/integration`):** [investigation-agent-integration-contract.md](./investigation-agent-integration-contract.md)
- Project scope, OSS gaps, and Saarthi Pro links: [investigation-agent-project.md](../projects/investigation-agent-project.md) · commercial vs OSS: [Saarthi Pro vs OSS](./saarthi-pro-vs-oss.md)
- Maintainer scanning overview: [security-scanning.md](./security-scanning.md)
- Vulnerability reporting: [SECURITY.md](../../../SECURITY.md) (repo root)
