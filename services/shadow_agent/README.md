# tarka-shadow-agent

**Canonical Shadow HTTP surface** for the ingest rail: FastAPI `POST /v1/analyze`, audit persistence,
LLM backends via ``SHADOW_LLM_BACKEND`` (default **ollama**):

| Value | Endpoint | Key |
|-------|----------|-----|
| `ollama` | native `/api/chat` (`OLLAMA_HOST`, default `http://localhost:11434`) | optional `OLLAMA_API_KEY` |
| `self-hosted` / `vllm` | `SHADOW_LLM_BASE_URL` (OpenAI-compatible, e.g. `http://vllm:8000/v1`) | optional `SHADOW_LLM_API_KEY` |
| `claude` | Anthropic OpenAI-compat (`https://api.anthropic.com/v1`) | `ANTHROPIC_API_KEY` |
| `gemini` | Gemini OpenAI-compat | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| `qwen` | DashScope compatible-mode | `DASHSCOPE_API_KEY` |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |

Override model with ``SHADOW_LLM_MODEL``. Evaluate (`POST /v1/analyze`) uses this client. Shadow still **advises only**.

Unknown ``SHADOW_LLM_BACKEND`` values (for example ``azure``) **fail closed** — they do not fall through to laptop Ollama. For in-tenant Azure/Vertex/Bedrock-compatible OpenAI APIs use ``self-hosted`` / ``vllm`` plus ``SHADOW_LLM_BASE_URL``. ``TARKA_DEPLOYMENT_PROFILE=production`` refuses public ``api.openai.com`` / ``api.anthropic.com``.

Brand map (vs library `services/shadow` and desktop `tools/shadow`): [`../SHADOW.md`](../SHADOW.md).

Container build: see `Dockerfile` (context = repo root).

## Analyst force-multiplier (not omniscient autonomy)

On LLM timeout, `evaluate` returns an **inconclusive** decision (`risk_score=50`, `confidence_metrics.timeout_fallback=true`, reasoning `TIMEOUT_FALLBACK`) — never a clear-looking `risk_score=0` that could flip FLAG→ALLOW upstream. Orchestrator defaults treat Shadow as escalate-only advisory; see `services/orchestrator/README.md`.
