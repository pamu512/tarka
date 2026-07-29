# Fraud spine Phase 2 — Wave C design

Approved via Phase 2 wave table (2026-07-29). Scope: policy packing.

## Goal

One **policy set** identity that versions JSON rule packs + typology definitions +
challenge policies together, exposed on evaluate posture and evaluate responses.

## Shape

- Module `decision_api/policy_set.py`
  - Canonical manifest schema `tarka.policy_set/v1`
  - `policy_set_id` = sha256 of sorted component digests
  - Cache invalidated when rules / typology / challenge policies reload
- `GET /v1/policy/posture` → full manifest (ops / Trust Center)
- `EvaluateResponse.policy_set_id` + artifact_manifest / audit snapshot

## Out of scope

Pack deploy API, GitOps promote, enforcement adapters (Wave D).
