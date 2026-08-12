# tarka-shadow-agent

**Canonical Shadow HTTP surface** for the ingest rail: FastAPI `POST /v1/analyze`, audit persistence,
OpenAI-compatible LLM backends via ``SHADOW_LLM_BACKEND`` (``openai`` | ``ollama``; unset defaults to ollama).

Brand map (vs library `services/shadow` and desktop `tools/shadow`): [`../SHADOW.md`](../SHADOW.md).

Container build: see `Dockerfile` (context = repo root).

## Analyst force-multiplier (not omniscient autonomy)

On LLM timeout, `evaluate` returns an **inconclusive** decision (`risk_score=50`, `confidence_metrics.timeout_fallback=true`, reasoning `TIMEOUT_FALLBACK`) — never a clear-looking `risk_score=0` that could flip FLAG→ALLOW upstream. Orchestrator defaults treat Shadow as escalate-only advisory; see `services/orchestrator/README.md`.
