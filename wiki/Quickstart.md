# Quickstart

## Prerequisites

- Docker + Docker Compose
- Python 3.11+
- Git

## Option 1: Full stack

```bash
python tarka.py install --full
python tarka.py start
```

## Option 2: Select modules

```bash
python tarka.py install --modules core,cases,graph,ml
python tarka.py start
```

## Verify

- Decision API health: `GET /api/decisions/v1/health`
- Case API health: `GET /api/cases/v1/health`
- Frontend: open the configured local frontend URL
- Integration ingress health: `GET /api/ingress/v1/health`

## First evaluation example

Send a decision request to:

`POST /api/decisions/v1/decisions/evaluate`

with:
- `tenant_id`
- `event_type`
- `entity_id`
- optional `payload`
- optional `device_context`

## Integrations Demo (Local)

1. Open the frontend and navigate to `Integrations`.
2. Pick a provider and click `Configure`.
3. Enter **either**:
   - `api_key`, or
   - `username` + `password`.
4. Save, then click `Test` to run connectivity validation.
5. Confirm integration status and health score update.

## KMS Demo (Local and Cloud)

- Local mode (default): no cloud setup needed.
- AWS mode: set `KMS_PROVIDER=aws`, `AWS_KMS_REGION`, `KMS_ACTIVE_KEY_ID`.
- GCP mode: set `KMS_PROVIDER=gcp`, `GCP_KMS_KEY_RESOURCE`.
- Azure mode: set `KMS_PROVIDER=azure`, `AZURE_KEY_VAULT_URL`, `AZURE_KMS_KEY_NAME`.

Useful endpoints:

- `GET /api/ingress/v1/vault/kms`
- `GET /api/ingress/v1/vault/kms/self-check`
- `POST /api/ingress/v1/vault/rotate`
