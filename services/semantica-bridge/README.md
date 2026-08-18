# Semantica bridge (optional)

Mirrors Tarka decision-context records into Semantica for demo/export.

| Env | Default | Meaning |
|-----|---------|---------|
| `SEMANTICA_BRIDGE_ENABLED` | `0` | Off |
| `SEMANTICA_PIN` | required if real package used | Package version or git SHA |

Never on the evaluate allow/deny path. Stub backend works without installing Semantica.

```bash
export SEMANTICA_BRIDGE_ENABLED=1
PYTHONPATH=services/semantica-bridge python -c "from semantica_bridge import mirror_decision; print(mirror_decision(category='x', scenario='y', reasoning='z', outcome='ok'))"
```
