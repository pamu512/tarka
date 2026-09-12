# Observe and Shadow agent (LLM advise)

Tarka has **two** features. They are not one brand with three paths. The old write-up named only the LLM sidecar and skipped observe-only evaluate.

| Feature | What people say | What it is |
|---------|-----------------|------------|
| **Observe** (observe-only evaluate) | **Observe**. Docs may say “shadow mode.” Pack promote stays **Canary**. Never call this “Shadow agent.” | Same `POST /v1/decisions/evaluate` path with no live side effects. The wire field is `metadata.shadow`. Pack canary records a candidate pack; allow/deny still comes from the live pack. Guide: [Observe / A/B](../docs/docs/guides/shadow-and-ab-testing.md). |
| **Shadow agent (LLM advise)** | On the desk: **Advise** is investigation-agent only. Operator docs say **Shadow agent (LLM advise)** here for the ingest sidecar. Never a model brand. Never on lean nav. | Ingest sidecar: `POST /v1/analyze`, audit write. Package `tarka-shadow-agent` in [`shadow_agent/`](shadow_agent/). Orchestrator hooks live in [`orchestrator/shadow/`](orchestrator/shadow/) (`tarka-shadow` library). Wired from orchestrator via existing `SHADOW_AGENT_URL`. |

Desk Advise is **investigation-agent** (`OPENAI_BASE_URL` + `OPENAI_API_KEY` [+ `OPENAI_MODEL`]). Empty URL = plane off; hide chrome. Ingest Advise is `SHADOW_LLM_*` / `SHADOW_AGENT_URL`. Do not smash the two.

There is no desktop forensics console in this repo. Do not add a third Advise path.

## Naming rules

- RFP and docs INDEX: “shadow mode” means **Observe** only, not the LLM.
- Desk copy for the LLM is **Advise**. Do not invent a third brand.
- Code imports `from shadow.…` still mean the library under orchestrator / `services/shadow`.
- Do not rename JSON fields, tags, SQL, Helm keys, or compose services.
- Never name a new compose service `shadow` without a suffix (`shadow_agent`).

## Advise context (planned)

Future path: Confluence / Wiki **read-only** sync into tenant OKF / RAG. Other knowledge connectors on request. SOP zip upload remains the air-gap bootstrap. Built-in playbooks are generic defaults only when the desk provides none — desks should bring their own SOPs. This repo does not ship a Confluence connector.
