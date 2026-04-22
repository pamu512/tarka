from __future__ import annotations

"""OpenAI-compatible embedding API for RAG (async)."""


import httpx


async def embed_texts(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    base_url: str,
    model: str,
    texts: list[str],
) -> list[list[float]]:
    """
    Batch embed inputs. Truncates each string for safety.
    Returns one vector per input (same order).
    """
    if not api_key or not texts:
        return []
    url = f"{base_url.rstrip('/')}/embeddings"
    # API limit: batch size; keep <= 64 per request
    out: list[list[float]] = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        batch = [t[:8000] for t in texts[i : i + batch_size]]
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": batch},
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError("embeddings response missing data[]")
        # Sort by index in case API reorders
        indexed: list[tuple[int, list[float]]] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            idx = int(item.get("index", 0))
            emb = item.get("embedding")
            if isinstance(emb, list) and all(isinstance(x, (int, float)) for x in emb):
                indexed.append((idx, [float(x) for x in emb]))
        indexed.sort(key=lambda x: x[0])
        out.extend(v for _, v in indexed)
    if len(out) != len(texts):
        raise ValueError(f"embedding count mismatch: got {len(out)} expected {len(texts)}")
    return out


def cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)
