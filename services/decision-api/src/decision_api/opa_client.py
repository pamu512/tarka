from typing import Any

import httpx


async def evaluate_opa(http: httpx.AsyncClient, opa_url: str, input_payload: dict[str, Any]) -> dict[str, Any] | None:
    if not opa_url:
        return None
    url = opa_url.rstrip("/") + "/v1/data/fraud/result"
    try:
        r = await http.post(url, json={"input": input_payload}, timeout=2.0)
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("result")
    except httpx.HTTPError:
        return None
