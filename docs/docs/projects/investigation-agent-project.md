# Investigation Agent Project

## Scope

Workflow assistant capabilities for case triage, evidence gathering, and analyst productivity.

**Distribution:** The **canonical agent implementation** is **`services/investigation-agent`** in **this repo** (codename **Saarthi**). Build a **minimal agent image** with **`services/investigation-agent/Dockerfile`** from the repo root (CI **`docker-build`** includes this target). **[Saarthi-pro](https://github.com/pamu512/Saarthi-pro)** is the **private commercial** product repo (`saarthi_pro.asgi`, **`/v1/pro`**, license middleware, Dockerfile cloning Tarka, registry/`RELEASE.md`); see its README when you have access. Commercial releases **pin** a Tarka commit and **`contract_version`** ([distribution & contract parity](../guides/saarthi-pro-distribution-and-contract-parity.md)); Saarthi-pro does not replace the OSS source of truth for core copilot behavior.

**Saarthi Pro (what buyers get):** Same copilot **behavior** and integration contract as the OSS reference; **vendor** packaging (SLAs where sold, signed DPA/subprocessor story, maintained **adapters** on supported tiers, release branding). Full comparison → **[Saarthi Pro vs OSS](../guides/saarthi-pro-vs-oss.md)**. Phased commercial plan and artifact index → **[Saarthi Pro roadmap](../guides/saarthi-pro-roadmap.md)**. Adapter-first economics (illustrative bands; **internal** until finance/legal sign quotes) → [adapter strategy & pricing](../guides/saarthi-pro-adapter-strategy-and-pricing.md).

## Current gaps (OSS reference)

| Area | Limitation |
|------|------------|
| **Grounding & hallucinations** | **Claims** trailer + heuristic downgrade of `source=tool`; **token-overlap** hints (`claims_deterministic_support`); optional **LLM judge** pass; prose is still **not** formally verified. Truncation and tool errors can still yield confident wrong narratives. |
| **Prompt injection & untrusted context** | Regex/sanitization + optional reject; client **`platform_audit`** remains supply-chain into context (mitigated, not removed). Assistant history sanitized as untrusted. |
| **Data residency / subprocessors** | Chat, audit, and tool payloads can reach your configured LLM URL (**BYOK**). Controls = env flags + network + your DPIA. |
| **Auth & blast radius** | Dev-friendly defaults (`ALLOWED_ANALYSTS=*`, optional empty `API_KEYS`); shared `upstream_api_key` if configured. Hardening knobs exist (`COPILOT_REQUIRE_INVESTIGATION_API_KEY`, tool denylist). |
| **Powerful tools** | Replay, label export/ingest, graph, case APIs—safety is **upstream API auth + network + RBAC**. |
| **Product UX & cost** | **SSE** `POST /v1/chat/stream`; sync chat adds **turn_id**, **feedback** endpoint, **evidence_bundle_draft**; offline mode is a single string; token caps **env-level**. |
| **Evidence & benchmarks** | **Shipped:** `evidence_bundle_draft` with **v1/dual** (`schema_id` `tarka.evidence_bundle/v1`), `contract_version`, `tool_trace_redacted`, `content_sha256`; JSON Schema in `contracts/schemas/tarka-evidence-bundle-v1.schema.json`. **Still limited:** no adoption of an **external** industry litigation/evidence-pack standard; no shipped **scorecards** vs human labels; investigation **label drafts** ≠ case workflow labels. **v1 does not** certify factual correctness of prose. |

**Regional builds:** `AI_GOVERNANCE_PROFILE` overlays and `GET /v1/governance` are **in-repo configuration** for policy wording and deployment profiles. See [AI governance regional builds](../guides/ai-governance-regional-builds.md).

**Intended use, out of scope, and data-flow map** (prompts, LLM, RAG, feedback, review DB, logs—plus how regional builds fit): [investigation-agent-intended-use-and-data-flows.md](../guides/investigation-agent-intended-use-and-data-flows.md).

**Integration contract (adapter parity):** `GET /v1/integration`, `integration` block on `GET /v1/health`, env `INTEGRATION_PROFILE_ID` — [investigation-agent-integration-contract.md](../guides/investigation-agent-integration-contract.md).

**Shipped in tree (keep docs in sync):** tool loop to case-api (cases, disputes), graph, decision-api (audit, entity-velocity, replay); **paired replay** via `trace_ids`; **durable label drafts** via `/v1/investigation-label-drafts`; export of weak labels from cases/disputes; **tool-quality** metrics + structured logs per chat; **batch tabular jobs** via `POST /v1/batch/ingest` (CSV, JSON, NDJSON, XLSX) and tools `get_batch_profile`, `query_batch_rows`, `aggregate_batch_column` (tenant + analyst scoped, in-memory TTL); **investigation memos** via `POST /v1/knowledge/ingest` + tool `search_knowledge` with **SQLite-backed chunks** under `INVESTIGATION_DATA_DIR` (optional **hybrid RAG**: embeddings when `OPENAI_API_KEY` is set and `copilot_knowledge_embeddings` is true; `copilot_rag_keyword_weight`, `copilot_embedding_model`, `COPILOT_RAG_DB_NAME`); **deterministic queue snapshot** tool `compare_entity_queue_snapshot` (entity velocity + `list_cases` window overlap); **structured answer sections** (Markdown headings FACTS / INFERENCES / UNKNOWNS / NEXT STEPS, toggle `COPILOT_STRUCTURED_SECTIONS`); **claims_deterministic_support** + **tool_acknowledgment_warnings** on each chat; optional **judge pass** (`COPILOT_ENABLE_JUDGE_PASS`, `OPENAI_JUDGE_MODEL`); **evidence_bundle_draft** on each turn (**v0 / v1 / dual**, see `COPILOT_EVIDENCE_BUNDLE_FORMAT`); **POST /v1/feedback** with **SQLite persistence** (`COPILOT_FEEDBACK_DB_NAME`), optional `tenant_id`/`analyst_id` on the body, **`GET /v1/feedback/summary`** and **`GET /v1/feedback/recent`** for analytics; optional **analytics events** (`COPILOT_ANALYTICS_*`: turn completed, feedback submitted); **strict assurance mode** (`COPILOT_ASSURANCE_MODE=strict`) withholds model prose when tool errors are unacknowledged or tool-claims fail deterministic support; optional **`derived_facts`** (server-extracted tool scalars, `COPILOT_DERIVED_FACTS` or strict); **POST /v1/review/turn** and **GET /v1/review/turn** for **human sign-off** records (`COPILOT_REVIEW_DB_NAME`); **POST /v1/chat/stream** (SSE); **maker–checker for sensitive tools** when `COPILOT_REVIEWER_SECRET` is set (hides `ingest_labeled_rows` / `run_replay_ab_comparison` unless `x-reviewer-secret` matches); **typology playbooks** via `GET /v1/playbooks` and optional `playbook_id` on chat; **source reference cards** (`source_refs`); **regional AI governance builds** (`AI_GOVERNANCE_PROFILE=us|eu_uk|global`) with `GET /v1/governance` and compose/Helm profiles under `deploy/profiles/ai-governance/` (see [AI governance regional builds](../guides/ai-governance-regional-builds.md)). Optional **production hardening** overlay: `deploy/docker-compose.production-hardening.yml`. **Prompt contract version** in `GET /v1/health` (`copilot_prompt_version`, `copilot_features` includes `knowledge_embeddings`, `feedback_persistence`, `assurance_mode`, `derived_facts`, `turn_review_persistence`, `evidence_bundle_format`, `evidence_bundle_v1`, `analytics_*`).

**Assurance (optional):** `COPILOT_ASSURANCE_MODE=standard|strict` (strict refusal when tool errors are unacknowledged in prose or tool-sourced claims lack deterministic overlap with tool JSON); `COPILOT_DERIVED_FACTS` (include server-extracted `derived_facts` on chat; implied in strict); human sign-off **`POST /v1/review/turn`** + **`GET /v1/review/turn`** (SQLite `COPILOT_REVIEW_DB_NAME`). Guide: [investigation-agent-assurance-modes.md](../guides/investigation-agent-assurance-modes.md).

**Copilot hardening (OSS env):** `COPILOT_INJECTION_POLICY` (`sanitize` \| `reject`), `COPILOT_INCLUDE_PLATFORM_AUDIT_IN_PROMPT`, `COPILOT_REQUIRE_INVESTIGATION_API_KEY`, `COPILOT_MAX_TOOL_ITERATIONS`, `COPILOT_MAX_COMPLETION_TOKENS`, `COPILOT_ENFORCE_TOOL_CLAIM_GROUNDING`, `COPILOT_DISABLED_TOOLS`, `COPILOT_HIDE_TOOLS_WITHOUT_UPSTREAM` (default true — hide tools whose upstream URL is unset), `COPILOT_STRUCTURED_SECTIONS`, `COPILOT_ENABLE_JUDGE_PASS`, `OPENAI_JUDGE_MODEL`, `COPILOT_JUDGE_MAX_TOKENS`, `COPILOT_REVIEWER_SECRET`, `COPILOT_SENSITIVE_TOOLS`, `KNOWLEDGE_TTL_SECONDS`, `COPILOT_PROMPT_VERSION`, `COPILOT_ASSURANCE_MODE`, `COPILOT_DERIVED_FACTS`, `COPILOT_REVIEW_DB_NAME`, **`COPILOT_EVIDENCE_BUNDLE_FORMAT`** (`v0` \| `v1` \| `dual`, default **dual**), **`AGENT_BUILD_ID`**, **`COPILOT_EVIDENCE_REDACTION_LEVEL`** (`none` \| `analyst_view` \| `export_safe`), **`COPILOT_ANALYTICS_ENABLED`**, **`COPILOT_ANALYTICS_SINK`** (`log` \| `http`), **`COPILOT_ANALYTICS_WEBHOOK_URL`**, **`COPILOT_ANALYTICS_HMAC_SECRET`**. Integration changelog: [CHANGELOG_INTEGRATION](../guides/CHANGELOG_INTEGRATION.md). Details: [investigation-agent-llm-data-flow.md](../guides/investigation-agent-llm-data-flow.md).

## Roadmap

**Saarthi Pro (commercial packaging, procurement, certification):** see [Saarthi Pro roadmap](../guides/saarthi-pro-roadmap.md). The bullets below are **OSS reference** priorities in this repo.

### Now

- Extend **evidence_bundle** toward **external** evidence-pack or review workflows when a sector schema lands; tighten deterministic traces and scorecard hooks for analyst trust (see [evidence bundle v1 alignment spec](../guides/saarthi-pro-evidence-bundle-v1-alignment.md)—v1 fields already shipped in OSS).
- Add guardrails for action suggestions and policy-safe defaults.

### Next

- Add case pattern recall and escalation quality feedback loops.
- Integrate richer evidence packaging into review workflows.

### Later

- Semi-autonomous triage playbooks with strict human-in-the-loop boundaries.
