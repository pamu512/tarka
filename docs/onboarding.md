# Engineer onboarding

This guide walks you through the **Nix development shell**, applying the **Triple-DB Pulumi stack** against **local** databases with a **filesystem Pulumi backend**, and running your first **Shadow Rule** regression test.

---

## Prerequisites

| Requirement | Notes |
|---------------|--------|
| [Nix](https://nixos.org/download/) with **flakes** enabled (`experimental-features = nix-command flakes`) | Required for `nix develop`. |
| [Pulumi CLI](https://www.pulumi.com/docs/install/) | Not bundled in the flake; install globally or run `nix shell nixpkgs#pulumi`. |
| Python **3.11+** | Used by `deploy/pulumi` (virtualenv) and Python services. |
| **kubectl** context targeting a cluster | Only if you run full `pulumi up` with the default Redis backend (`triple-db:redisBackend: kubernetes` in `deploy/pulumi/Pulumi.dev.yaml`). Docker Desktop Kubernetes or [kind](https://kind.sigs.k8s.io/) is enough for local Redis. |

Architecture notes for Pulumi live in [`0003-iac-via-pulumi` ADR](docs/adr/0003-iac-via-pulumi.md).

---

## 1. Enter the Nix development shell

From the repository root:

```bash
nix develop
```

What you get:

- **Rust** toolchain (stable, with `clippy`), **Cargo** helpers (`cargo-edit`, `cargo-watch`).
- **Poetry** and Python **3.11** with `poetry-core`.
- **PostgreSQL 15**, **Redis**, and **ClickHouse** client binaries on `PATH`.
- **Optional auto-start** of local databases: on shell entry, `tarka_dbs up -D` runs **process-compose** (Postgres on **5432**, Redis on **6379**, ClickHouse HTTP on **8123** unless configured otherwise).  
  - If ports conflict or you manage services yourself, skip auto-start:  
    `TARKA_SKIP_LOCAL_DB=1 nix develop`

Supported platforms from `flake.nix`: **aarch64-darwin**, **aarch64-linux**, **x86_64-linux**.

Sanity checks (optional):

```bash
pg_isready -h 127.0.0.1 -p 5432
redis-cli -h 127.0.0.1 -p 6379 ping
curl -sS 'http://127.0.0.1:8123/ping' || true
```

---

## 2. Pulumi: local backend and `pulumi up`

The stock Pulumi CLI does **not** define `pulumi up --local`. What teams usually mean is:

1. Store stack state **locally** (no Pulumi Cloud account): **`pulumi login --local`** (filesystem backend).
2. Apply the stack: **`pulumi up`**.

Together, that is “run Pulumi locally.”

### 2.1 Install dependencies and select the dev stack

```bash
cd deploy/pulumi
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

pulumi login --local
pulumi stack select dev --create   # first time; afterwards: pulumi stack select dev
```

Stack defaults live in `deploy/pulumi/Pulumi.dev.yaml` (Postgres/ClickHouse/Redis pointing at **localhost**).

### 2.2 Required secret

The Postgres provider needs a password (secret):

```bash
pulumi config set --secret triple-db:postgresPassword '<your-local-password>'
```

Use credentials that match your **local** Postgres role configured in the stack (`triple-db:postgresUser`, default `tarka` in `Pulumi.dev.yaml`). If you only use the databases started by `nix develop`, align this with how your Postgres instance authenticates that user.

### 2.3 Kubernetes for Redis (default stack)

`Pulumi.dev.yaml` sets `triple-db:redisBackend: kubernetes`. A successful **`pulumi up`** creates Redis **in the cluster** pointed to by your current **`kubectl` context**. Ensure a context is selected (`kubectl config current-context`) and that you can create namespaces/workloads.

If you are not ready to use Kubernetes, you can still complete **Section 3** (the Shadow Rule test is a **unit test** and does not require Pulumi or running services).

### 2.4 Apply the stack

```bash
pulumi up
```

On success, export FastAPI-oriented connection material (optional for local services):

```bash
pulumi stack output tripleDbDotenv --show-secrets > ../../.env.triple-db
```

Do **not** commit `--show-secrets` output. Merge keys into service `.env` files as needed.

---

## 3. First Shadow Rule test

“Shadow” rules are packs with **`mode: shadow`**: they are evaluated for comparison and telemetry but do not drive production decisions by themselves. The shipped ROI packs include a probe rule used in regression tests.

With the Nix shell active (or any environment where Python dependencies are installed):

```bash
cd services/decision-api
pip install -e ".[dev]"
pytest tests/test_roi_rule_packs.py::TestROIRulePacksLoaded::test_shadow_probe_pack_is_shadow_not_active -v
```

What this proves:

- Rule packs under `services/decision-api/rules` parse and load.
- The rule **`shadow_probe_high_amount_only`** appears under **shadow** packs (`get_shadow_packs()`), not in the active production pack list.

Expected: **one passed test**.

---

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| `nix develop` fails | Flakes enabled? Correct architecture supported by `flake.nix`? |
| `tarka_dbs up -D` fails | Ports 5432 / 6379 / 8123 in use — stop conflicting services or `TARKA_SKIP_LOCAL_DB=1`. |
| `pulumi up` fails on Redis | Valid `kubectl` context? Namespace permissions? Or defer full stack and run Section 3 only. |
| Postgres auth errors during `pulumi up` | `pulumi config set --secret triple-db:postgresPassword` matches your local DB user. |
| Shadow test import errors | Run from `services/decision-api`, `pip install -e ".[dev]"`, repo layout intact (`rules/` present). |

---

## Next steps

- Broader local stack: [Quickstart](docs/quickstart.md) (Docker Compose paths).
- Decision API behavior and ports: [decision-api service doc](docs/services/decision-api.md).
- Forensic / UI “Shadow” add-on (optional submodule): [local forensics suite](docs/guides/local-forensics-suite.md).
