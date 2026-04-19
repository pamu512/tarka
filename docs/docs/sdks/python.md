# Python SDK

The Python SDK (`tarka-sdk`) provides a server-side client for the Decision API with optional IP/geo signal collection. Use it in your backend to evaluate fraud decisions for incoming requests.

**Package:** `tarka-sdk`
**Python:** ≥ 3.11
**Dependencies:** `httpx`

---

## Installation

```bash
pip install tarka-sdk
```

Or install from source:

```bash
cd packages/fraud-sdk-python
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

---

## Basic Usage

### Synchronous

```python
from fraud_stack_sdk import DecisionClient

client = DecisionClient(
    base_url="http://localhost:8000",
    api_key="your-api-key",
)

result = client.evaluate(
    tenant_id="acme",
    event_type="payment",
    entity_id="user-42",
    payload={
        "amount": 499.99,
        "currency": "USD",
        "merchant": "electronics-store",
    },
)

print(result["decision"])  # "allow", "review", or "deny"
print(result["score"])     # 0–100
print(result["trace_id"])  # UUID for audit trail
```

### Event ingest (async NATS path)

For high write volume, send events to **event-ingest**; a worker forwards them to the Decision API. Optional **`idempotency_key`** maps to the **`Idempotency-Key`** header when Redis is enabled on ingest.

```python
from fraud_stack_sdk import EventIngestClient

ingest = EventIngestClient("http://localhost:8007", api_key="your-api-key")
ack = ingest.send_event(
    "acme",
    "login",
    "user-42",
    payload={"ip": "203.0.113.10"},
    idempotency_key="optional-client-request-id",
)
print(ack["ingest_id"])
```

See **[Ingest, idempotency & replay](../guides/ingest-replay-onboarding.md)** for ports, metrics, and the offline replay script.

### Asynchronous

```python
import asyncio
from fraud_stack_sdk import DecisionClient

client = DecisionClient(
    base_url="http://localhost:8000",
    api_key="your-api-key",
)

async def check_payment():
    result = await client.evaluate_async(
        tenant_id="acme",
        event_type="payment",
        entity_id="user-42",
        payload={"amount": 499.99, "currency": "USD"},
    )
    return result

result = asyncio.run(check_payment())
```

---

## Resilient evaluate envelope (Issue #43)

`evaluate` / `evaluate_async` send **canonical JSON** (`sort_keys=True`, compact separators) as the raw body so **retries and HMAC** see the same bytes. Optional knobs:

| Mechanism | How |
|-----------|-----|
| **Idempotency** | `idempotency_key="..."` → `Idempotency-Key` header (safe client-side retries when your gateway supports it). |
| **Replay hints** | `replay_safe_headers=True` adds `X-Tarka-Client-Nonce` (UUID) and `X-Tarka-Client-Timestamp` (unix seconds); override with `client_nonce` / `client_timestamp`. |
| **HMAC signing** | `DecisionClient(..., request_signing_secret="shared-secret")` adds `X-Tarka-Timestamp` + `X-Tarka-Signature` per [TLS pinning & signed requests](../guides/tls-pinning-and-signed-requests.md). |
| **Strict response** | `DecisionClient(..., strict_evaluate_response=True)` validates JSON against the evaluate contract and raises `EvaluateResponseValidationError` on drift. |

Lower-level helpers (same module as `DecisionClient` exports):

```python
from fraud_stack_sdk import (
    build_evaluate_envelope,
    canonical_json_bytes,
    build_evaluate_request_headers,
    parse_evaluate_response,
)

body = build_evaluate_envelope(tenant_id="t", event_type="login", entity_id="e", payload={"x": 1})
raw = canonical_json_bytes(body)
headers = build_evaluate_request_headers(
    api_key="key",
    body_bytes=raw,
    idempotency_key="pay-123",
    client_nonce="custom-nonce",
    client_timestamp=1700000000,
)
```

**Module swimlane:** SDK Python (GitHub **#43**, `borrowed-from-OSS`).

---

## Server-Side Signal Collection

The Python SDK includes a `ServerSignalCollector` that extracts signals from the incoming HTTP request (IP address, proxy headers, datacenter detection, bot user-agent patterns).

### Automatic Collection

Enable `server_signals=True` and pass the client IP:

```python
client = DecisionClient(
    base_url="http://localhost:8000",
    api_key="your-api-key",
    server_signals=True,
)

result = client.evaluate(
    tenant_id="acme",
    event_type="login",
    entity_id="user-42",
    payload={"ip": request.client.host},
    client_ip=request.client.host,
    request_headers=dict(request.headers),
)
```

When `server_signals=True`, the SDK automatically:

1. Extracts the client IP and checks for proxy headers (`X-Forwarded-For`, `Via`, `X-Real-IP`)
2. Detects datacenter IPs from known ASN ranges (AWS, GCP, Azure, DigitalOcean, etc.)
3. Detects bot user-agents (curl, wget, python-requests, crawler patterns)
4. Generates a `device_id` from IP + User-Agent hash
5. Packages everything into a `device_context` with `platform: "server"`

### Manual Collection

For more control, use the `ServerSignalCollector` directly:

```python
from fraud_stack_sdk import ServerSignalCollector

collector = ServerSignalCollector()

signals = collector.collect(
    ip="203.0.113.42",
    headers={
        "user-agent": "Mozilla/5.0 ...",
        "x-forwarded-for": "1.2.3.4",
    },
    asn="AS16509",       # optional: AWS ASN
    country="US",        # optional: GeoIP country
)
```

**Returned signals:**

```python
{
    "ip_address": "203.0.113.42",
    "ip_forwarded_for": "1.2.3.4",
    "ip_geo_country": "US",
    "ip_asn": "AS16509",
    "ip_is_proxy": True,
    "ip_is_datacenter": True,
    "is_bot": False,
    "user_agent": "Mozilla/5.0 ...",
}
```

### Merging Client + Server Signals

If your frontend SDK also collects signals (via the TypeScript SDK), you can merge them:

```python
device_context = collector.build_device_context(
    ip=request.client.host,
    headers=dict(request.headers),
    client_device_context=request_body.get("device_context"),
)

result = client.evaluate(
    tenant_id="acme",
    event_type="payment",
    entity_id="user-42",
    payload={"amount": 100},
    device_context=device_context,
)
```

The `build_device_context` method merges server-side signals with client-provided signals, with server signals taking precedence for fields like `ip_is_proxy` and `ip_is_datacenter`.

---

## Attestation

Verify device attestation tokens:

```python
result = client.validate_attestation(
    nonce="abc123...",
    token="signed-attestation-token",
    provider="play_integrity",
)
print(result["valid"])             # True/False
print(result["device_integrity"])  # "play_integrity", "browser", etc.
```

---

## Audit Trail

Retrieve audit records for a specific decision:

```python
audit = client.get_audit(trace_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
print(audit["decision"])     # "allow"
print(audit["score"])        # 10.0
print(audit["tags"])         # ["sdk:vpn"]
print(audit["created_at"])   # "2026-03-31T10:15:30"
```

---

## Framework Integration

### FastAPI

```python
from fastapi import FastAPI, Request
from fraud_stack_sdk import DecisionClient

app = FastAPI()
fraud_client = DecisionClient(
    base_url="http://localhost:8000",
    server_signals=True,
)

@app.post("/checkout")
async def checkout(request: Request):
    body = await request.json()
    user_id = body["user_id"]

    decision = await fraud_client.evaluate_async(
        tenant_id="acme",
        event_type="payment",
        entity_id=user_id,
        payload={"amount": body["amount"], "currency": body["currency"]},
        client_ip=request.client.host,
        request_headers=dict(request.headers),
    )

    if decision["decision"] == "deny":
        return {"error": "Transaction blocked"}, 403

    if decision["decision"] == "review":
        # proceed but flag for review
        pass

    return {"status": "ok", "trace_id": decision["trace_id"]}
```

### Django

```python
from fraud_stack_sdk import DecisionClient

fraud_client = DecisionClient(
    base_url="http://localhost:8000",
    api_key="your-api-key",
    server_signals=True,
)

def process_payment(request):
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() \
         or request.META.get("REMOTE_ADDR", "")

    headers = {
        "user-agent": request.META.get("HTTP_USER_AGENT", ""),
        "x-forwarded-for": request.META.get("HTTP_X_FORWARDED_FOR", ""),
    }

    decision = fraud_client.evaluate(
        tenant_id="acme",
        event_type="payment",
        entity_id=str(request.user.id),
        payload={"amount": request.POST["amount"]},
        client_ip=ip,
        request_headers=headers,
    )

    if decision["decision"] == "deny":
        return JsonResponse({"error": "blocked"}, status=403)

    return JsonResponse({"trace_id": decision["trace_id"]})
```

---

## API Reference

### `DecisionClient`

```python
DecisionClient(
    base_url: str,
    api_key: str = "",
    timeout: float = 10.0,
    server_signals: bool = False,
    *,
    request_signing_secret: str | None = None,
    strict_evaluate_response: bool = False,
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `base_url` | str | required | Decision API base URL |
| `api_key` | str | `""` | API key for `X-API-Key` header |
| `timeout` | float | `10.0` | Request timeout in seconds |
| `server_signals` | bool | `False` | Enable automatic server-side signal collection |
| `request_signing_secret` | str \| None | `None` | If set, sign evaluate POST body with HMAC headers |
| `strict_evaluate_response` | bool | `False` | If `True`, validate evaluate JSON before returning |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `evaluate(...)` | `dict` | Synchronous fraud evaluation |
| `evaluate_async(...)` | `dict` | Async fraud evaluation |
| `validate_attestation(nonce, token, provider)` | `dict` | Verify attestation token |
| `get_audit(trace_id)` | `dict` | Retrieve audit record |

### `ServerSignalCollector`

```python
ServerSignalCollector(geo_lookup_url: str = "")
```

#### Methods

| Method | Returns | Description |
|---|---|---|
| `collect(ip, headers, asn, country)` | `dict` | Extract server-side signals |
| `build_device_context(ip, headers, asn, country, client_device_context)` | `dict` | Build complete device_context with merged signals |

---

## Scorecard vs typical SDKs

Directional comparison (scores anchored near **3**): **[SDK scorecard — calibrated mid-scale](../guides/sdk-scorecard-2026-01.md)**.
