# Operations

## Common Commands

```bash
python tarka.py start
python tarka.py stop
python tarka.py status
python tarka.py logs
```

## Module Management

```bash
python tarka.py add --modules <module1,module2>
python tarka.py remove --modules <module1,module2>
```

## Upgrade Approach

1. Tag/backup current environment.
2. Apply updated configuration.
3. Start in shadow/simulation mode where possible.
4. Validate health and key decision paths.
5. Roll forward gradually.

## Production Hygiene

- Rotate API keys and secrets regularly.
- Use strict network boundaries between services.
- Monitor decision latency and denial/review rate drift.
- Keep alerting on ingest failures and queue lag.

## CodeQL and Workflow Runtime Notes

- Tarka uses repository-managed CodeQL workflow (`.github/workflows/codeql.yml`) for advanced setup.
- Default GitHub code scanning setup should remain disabled when using advanced setup, or SARIF uploads may be rejected.
- Java/Kotlin analysis is gated behind top-level build-file detection and manual build commands.
- Swift analysis uses explicit manual iOS simulator build steps.
- Workflow files are configured to force JavaScript actions to Node 24 for runtime compatibility.

## Integration Vault and KMS Runbook

### 1) Validate KMS config

- `GET /api/ingress/v1/vault/kms`
- `GET /api/ingress/v1/vault/kms/self-check`

If `config_valid=false` or self-check fails, fix provider-specific env values before proceeding.

### 2) Start rotation

```bash
curl -X POST http://localhost:8003/v1/vault/rotate \
  -H "Content-Type: application/json" \
  -d '{"new_key_id":"v-next","batch_size":200}'
```

### 3) Monitor rotation

- `GET /api/ingress/v1/vault/rotation-jobs`
- `GET /api/ingress/v1/vault/metrics`

Watch for:
- `status=completed`
- `failed=0`
- expected `processed/rotated` counts

### 4) Resume failed rotation

```bash
curl -X POST http://localhost:8003/v1/vault/rotate/resume \
  -H "Content-Type: application/json" \
  -d '{"job_id":"<job-id>"}'
```

### 5) Post-rotation checks

- Re-run `GET /api/ingress/v1/vault/kms/self-check`.
- Run sample integration connectivity tests from the Integrations UI.
- Confirm no new failures in rotation jobs list.
