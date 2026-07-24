# Quickstart

The canonical OSS quickstart lives in the docs site:

→ **[docs/docs/quickstart.md](../docs/docs/quickstart.md)**

One-liner from the repo root:

```bash
ALLOW_INSECURE_NO_AUTH=true docker compose -f infra/deploy/docker-compose.lite.yml up --build -d
```

Then evaluate at `http://127.0.0.1:8000/decisions/v1/decisions/evaluate` and open the UI.
