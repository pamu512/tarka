# Integrity + challenge ops (Waves A / B / C)

**Date:** 2026-08-01  
**Status:** Implemented (Waves A / B / C)

## Goal

Productize replay/tamper/MitM baseline and low-friction challenge readiness without new attestation providers.

## Waves

### Wave A — Prod integrity preset

- Compose hardening + env examples for `REQUEST_SIGNATURE_*`, `INTEGRITY_SOFT_TAGS`, replay TTL, challenge webhook placeholders.
- Governance / ingress status: signing required?, soft tags?, challenge webhook configured?.
- Doc pointer from tls-pinning guide.

### Wave B — Matrix on posture + evaluate signals

- `GET /v1/policy/posture` includes integrity ingress + matrix summary (policy_set_id unchanged).
- Middleware marks verified HMAC on `request.state`; evaluate emits `ingress:hmac_request_ok` / `replay_signature_ok` / soft missing tags.
- Ops UI page for matrix + ingress flags.

### Wave C — Challenge orchestration ops

- Hardening compose: `TARKA_CHALLENGE_WEBHOOK_*` commented placeholders.
- Ops surface: webhook configured + challenge policies.
- Contract test asserts webhook payload `schema_id` shape.

## Out of scope

Play Integrity / App Attest deep verify, new challenge providers, device-lab parity.
