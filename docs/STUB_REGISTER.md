# Stub Register

**Canonical inventory:** [`../STUB_REGISTER.md`](../STUB_REGISTER.md) (repo root).

This file is a pointer only so compliance/export paths that reference `docs/STUB_REGISTER.md` keep working. Do not maintain a second table here.

## CI gate

```bash
python3 scripts/audit_stubs.py
python3 infra/scripts/ci/test_audit_stubs.py
python3 scripts/audit_prod_desk_mocks.py
PYTHONPATH=scripts python3 infra/scripts/ci/test_audit_prod_desk_mocks.py
```

Wired in `.github/workflows/ci.yml`.
