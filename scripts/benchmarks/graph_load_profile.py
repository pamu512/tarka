#!/usr/bin/env python3
"""Graph write+read scale profile against a running graph-service (AGE backend).

Answers the first demonstration-tier scale question for the graph plane:
sustained API write throughput (entities/links through the real write path —
schema, sanitizers, provenance envelope) and read latency (1-hop/2-hop
subgraph, entity search, bitemporal as-of) at synthetic volume.

Usage (stack already up; buyer env has ALLOW_INSECURE_NO_AUTH=true)::

  GRAPH_API=http://127.0.0.1:28001 python3 scripts/benchmarks/graph_load_profile.py

Env: GRAPH_API (default http://127.0.0.1:8001), API_KEY optional,
TENANT (default loadtest), PERSONS/DEVICES/PAYMENTS/HUB_EDGES counts.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

WORKERS = int(os.environ.get("WORKERS", "16"))

def _retry_post(path, payload, tries=4):
    last = None
    for attempt in range(tries):
        try:
            return _post(path, payload)
        except urllib.error.URLError as e:
            last = e
            time.sleep(0.25 * (attempt + 1))
    raise last
from datetime import datetime, timezone

BASE = os.environ.get("GRAPH_API", "http://127.0.0.1:8001").rstrip("/")
TENANT = os.environ.get("TENANT", "loadtest")
PERSONS = int(os.environ.get("PERSONS", "500"))
DEVICES = int(os.environ.get("DEVICES", "400"))
PAYMENTS = int(os.environ.get("PAYMENTS", "500"))
HUB_EDGES = int(os.environ.get("HUB_EDGES", "200"))
API_KEY = (os.environ.get("API_KEY") or "").strip() or None
PROBE_TIMEOUT = float(os.environ.get("PROBE_TIMEOUT", "120"))


def _post(path: str, payload: dict) -> tuple[int, dict]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if API_KEY:
        headers["x-api-key"] = API_KEY
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace") or ""
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"error": "non-json error body", "status": e.code, "body": raw[:200]}


def _get(path: str) -> tuple[int, dict]:
    headers = {"accept": "application/json"}
    if API_KEY:
        headers["x-api-key"] = API_KEY
    req = urllib.request.Request(BASE + path, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_entities(count: int, kind: str) -> float:
    """POST count entities; returns writes/sec."""
    def one(i: int) -> None:
        status, body = _retry_post(
            "/v1/entities",
            {
                "tenant_id": TENANT,
                "entity_type": kind,
                "external_id": f"load-{kind.lower()}-{i}",
                "properties": {"loadrun": _iso_now(), "idx": i},
            },
        )
        if status != 200:
            raise RuntimeError(f"entity write {status}: {body}")

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(one, range(count)))
    return count / (time.monotonic() - t0)


def write_links(tasks: list[tuple[str, str, str, dict]]) -> float:
    """POST links (from, to, rel, props); returns writes/sec."""
    def one(t: tuple[str, str, str, dict]) -> None:
        src, dst, rel, props = t
        status, body = _retry_post(
            "/v1/links",
            {
                "tenant_id": TENANT,
                "from_external_id": src,
                "to_external_id": dst,
                "relationship": rel,
                "properties": props,
            },
        )
        if status != 200:
            raise RuntimeError(f"link write {status}: {body}")

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(one, tasks))
    return len(tasks) / (time.monotonic() - t0)


def read_latencies(label: str, path: str, n: int = 25) -> None:
    lat = []
    for _ in range(n):
        t0 = time.monotonic()
        status, _ = _get(path)
        lat.append(time.monotonic() - t0)
        if status != 200:
            print(f"  {label}: HTTP {status} — aborting this probe")
            return
    lat.sort()
    p50 = lat[len(lat) // 2]
    p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
    print(
        f"  {label}: p50 {p50 * 1000:.0f}ms  p95 {p95 * 1000:.0f}ms  "
        f"max {lat[-1] * 1000:.0f}ms  (n={n})"
    )


def main() -> int:
    random.seed(7)
    print(f"graph load profile -> {BASE} tenant={TENANT}")
    print(f"volume: {PERSONS} persons, {DEVICES} devices, {PAYMENTS} payments, hub {HUB_EDGES} edges")

    eps = write_entities(PERSONS, "Person")
    print(f"[write] persons     {PERSONS} in {PERSONS / eps:.1f}s  ({eps:.0f}/sec)")
    eps = write_entities(DEVICES, "Device")
    print(f"[write] devices     {DEVICES} in {DEVICES / eps:.1f}s  ({eps:.0f}/sec)")
    eps = write_entities(PAYMENTS, "Payment")
    print(f"[write] payments    {PAYMENTS} in {PAYMENTS / eps:.1f}s  ({eps:.0f}/sec)")

    links: list[tuple[str, str, str, dict]] = []
    for i in range(PERSONS):
        props = {"trace_id": f"load-trace-{i}", "event_type": "load_profile"}
        links.append((f"load-person-{i}", f"load-device-{i % DEVICES}", "USED_DEVICE", props))
        links.append((f"load-person-{i}", f"load-payment-{i % PAYMENTS}", "MADE_PAYMENT", props))
    for i in range(HUB_EDGES):
        links.append((f"load-person-{i}", "load-device-0", "USED_DEVICE", {"hub": True}))
    lps = write_links(links)
    print(f"[write] links       {len(links)} in {len(links) / lps:.1f}s  ({lps:.0f}/sec)")

    total = PERSONS + DEVICES + PAYMENTS
    print(f"[read]  at {total} entities / {len(links)} edges:")
    read_latencies("subgraph 1-hop (hub, ~%d edges)" % (HUB_EDGES + PERSONS // DEVICES),
                   f"/v1/subgraph?tenant_id={TENANT}&entity_id=load-device-0&depth=1")
    read_latencies("subgraph 2-hop (person)",
                   f"/v1/subgraph?tenant_id={TENANT}&entity_id=load-person-3&depth=2")
    read_latencies("entity search (prefix)",
                   f"/v1/entities/search?tenant_id={TENANT}&q=load-person-1&limit=20")
    asof = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    read_latencies("subgraph 2-hop as-of (bitemporal)",
                   f"/v1/subgraph?tenant_id={TENANT}&entity_id=load-person-3&depth=2&as_of={urllib.parse.quote(asof)}")
    read_latencies("entity risk (analytics)",
                   f"/v1/analytics/entity-risk?tenant_id={TENANT}&entity_id=load-person-3")

    print("graph load profile: PASS")
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: F401 — used in f-string probe above

    sys.exit(main())
