Tenant OKF overlays are mounted here for local quickstart runs.

This directory is intentionally empty in the repository. Approved tenant bundles
must be supplied by operators and mounted read-only into the investigation-agent
container. Do not commit SOP payloads here.

Air-gap bootstrap (Confluence / Wiki sync is later):

```bash
python3 scripts/oss/advise_sop_import.py --zip /path/to/tenant-okf.zip --tenant-id YOUR_TENANT
# validate_okf_bundle --scope tenant must exit 0 before anything is staged
export OKF_TENANT_OVERLAYS_PATH=knowledge/tenants   # compose default
```

Compose mounts `${OKF_TENANT_OVERLAYS_PATH:-../../knowledge/tenants}` read-only as
`OKF_TENANT_ROOT`. Empty `OPENAI_BASE_URL` keeps the Advise plane off.
