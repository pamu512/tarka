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
