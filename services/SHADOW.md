# Observe and Shadow agent (LLM advise)

Tarka has **two** features. They are not one brand with three paths. The old write-up named only the LLM sidecar and skipped observe-only evaluate.

| Feature | What people say | What it is |
|---------|-----------------|------------|
| **Observe** (observe-only evaluate) | **Observe**. Docs may say “shadow mode.” Pack promote stays **Canary**. Never call this “Shadow agent.” | Same `POST /v1/decisions/evaluate` path with no live side effects. The wire field is `metadata.shadow`. Pack canary records a candidate pack; allow/deny still comes from the live pack. Guide: [Observe / A/B](../docs/docs/guides/shadow-and-ab-testing.md). |
| **Shadow agent (LLM advise)** | On the desk: **Advise**. Operator docs say **Shadow agent (LLM advise)** here, once. Never a model brand. Never on lean nav. | Local-first LLM sidecar. `POST /v1/analyze`, audit write, Ollama. Package `tarka-shadow-agent` in [`shadow_agent/`](shadow_agent/). Orchestrator hooks live in [`orchestrator/shadow/`](orchestrator/shadow/) (`tarka-shadow` library). Wired from orchestrator via existing `SHADOW_AGENT_URL`. |

The desktop console ([`../tools/shadow/`](../tools/shadow/)) is a specialist workstation for **Advise** (Vite/Tauri + local sidecar). It is not a third product and is not on default Lite / prod Helm.

## Naming rules

- RFP and docs INDEX: “shadow mode” means **Observe** only, not the LLM.
- Desk copy for the LLM is **Advise**. Do not invent a third brand.
- Code imports `from shadow.…` still mean the library under orchestrator / `services/shadow`.
- Do not rename JSON fields, tags, SQL, Helm keys, or compose services.
- Never name a new compose service `shadow` without a suffix (`shadow_agent`, `shadow-desktop`).
