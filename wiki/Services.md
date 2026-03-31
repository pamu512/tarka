# Services

## Decision API

- `/v1/decisions/evaluate`
- Rule evaluation, ML blending, list checks (whitelist/blacklist/test bypass)
- Captcha and device signal tags

## Case API

- Case lifecycle and workflow automation
- Dispute and chargeback automation
- SAR generation and audit history

## Graph Service

- Entity upsert and tagging
- Subgraph exploration
- Risk propagation and ring/community analytics

## ML Scoring

- Heuristic baseline scoring
- Adaptive anomaly detector
- Feedback hooks from dispute outcomes

## Integration Ingress

- Third-party KYC and enrichment adapters
- OSINT enrichment sources
- Integration Hub catalog and one-click enable/disable
- Connectivity testing (`api_key` OR `username` + `password`)
- Vault-backed masked credential config
- KMS endpoints:
  - `GET /v1/vault/kms`
  - `GET /v1/vault/kms/self-check`
  - `GET /v1/vault/metrics`
  - `GET /v1/vault/rotation-jobs`
  - `POST /v1/vault/rotate`
  - `POST /v1/vault/rotate/resume`

## Analytics Sink

- Decision stream ingestion
- Time-based and entity analytics endpoints
