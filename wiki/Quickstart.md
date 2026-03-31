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

## First evaluation example

Send a decision request to:

`POST /api/decisions/v1/decisions/evaluate`

with:
- `tenant_id`
- `event_type`
- `entity_id`
- optional `payload`
- optional `device_context`
