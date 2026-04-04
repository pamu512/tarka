# How to add a new OSINT source

Integration Ingress aggregates **IP, email, phone, and domain** signals in **`integration_ingress/osint.py`**, orchestrated from **`POST /v1/osint`** in `main.py`.

## Pattern

1. **Implement** an `async def osint_<category>_<vendor>(..., http: httpx.AsyncClient, cfg: OsintConfig) -> dict[str, Any]` that:
   - Returns a **small JSON-serializable dict** (scores, flags, raw snippets — avoid secrets).
   - Uses **`cfg`** for API keys (add fields on `OsintConfig` in the same module and wire env vars in `config.py` / `.env.example`).
   - Catches errors and returns `{"error": "..."}` or empty partials so **parallel** aggregation never fails the whole request.

2. **Register in the parallel batch** — e.g. for IP, append your coroutine to the `asyncio.gather` list inside the IP aggregation function so it runs **alongside** existing sources.

3. **Expose configuration** — add `requires_key` / `configured` entries in **`GET /v1/osint/sources`** in `main.py` so operators know whether the source is live.

4. **Test** — add a unit test under `services/integration-ingress/tests/` that mocks `httpx` and asserts your function handles success, 401, and timeouts.

## Adapter registry (KYC vs OSINT)

**KYC-style** verification adapters use **`integration_ingress/adapters.py`** (`ADAPTERS` dict + `register_adapter`). **OSINT** is separate; do not mix unless the UX is intentionally one funnel.

## Licensing and ToS

Document data retention, rate limits, and **redistribution** restrictions in your PR description. Prefer **official APIs** with clear fraud/cyber use terms.
