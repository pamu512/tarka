# Tarka

Tarka is a local-first fraud OS: evaluate packs + audit trail + analyst desk.

**Status:** beta. There is no GA tag. Development is on `master`.

## Day-1 (clone and run)

Tarka application code is **source-available** under the **Elastic License 2.0** (not open-source). After `git clone`:

```bash
make doctor && make demo
```

`make doctor` names Docker / port / RAM problems (host Postgres/Redis on `5432`/`6379`; stale `:8000` without `GET /decisions/v1/health`). `make demo` starts Lite + fraud-desk and prints one `NEXT:` URL plus `entity_id`. Receipts land on `/decisions`. Decisions are whatever the shipped packs return (ALLOW / REVIEW / DENY) — the walk does not invent them.

| Command | Skin | Notes |
|---------|------|--------|
| `make demo` | demo | First-hour pages. No `shadow_agent`. |
| `make product` | product | Analyst jobs + `desk_provision.json`. `shadow_agent` only when an LLM URL is set. |
| sales-only overlay | `VITE_DESK_PROFILE=brochure` | Pitch pages. Not the product default. |

P0: webhooks and product observe-notify are in `desk_provision.json` (empty URL = off). Helm prod-on-k8s keeps frontend / desk OFF and Shadow OFF. The `brochure` env token is unchanged.

Open the printed `NEXT:` link (Hunt with that person when graph is on). Receipts stay at `/decisions`. Observe is `/ops/shadow`.

Same scripts: `bash scripts/oss/up_desk.sh` (demo) or `bash scripts/oss/up_product.sh` (product). What you are looking at: [clone-and-run desk](docs/docs/guides/clone-demo.md). Product Day-1 (provision, hooks, Helm vs desk): [product Day-1 install](docs/docs/guides/product-day1-install.md). Deeper path: [15-minute first decision](docs/docs/guides/oss-15-minute-first-decision.md). Profiles: [SRE compose runbook](docs/docs/operations/sre-compose-profiles.md).

Desk home is `/graph` when graph is on. Receipts stay at `/decisions`.

- [Author a pack](docs/docs/guides/rules.md) — JSON rule packs (strategy analyst)
- [First evaluate](docs/docs/guides/oss-15-minute-first-decision.md) — `POST /decisions/v1/decisions/evaluate`

```
Can-run
Compose fraud-desk is day-1.
Helm prod-on-k8s is core-api HA
(replicaCount 2, tenant binding on).
investigation-agent ON (postgres, 2 replicas).
frontend / desk OFF.
Shadow OFF (no model in the chart;
operator BYO URL later, no Tarka-branded model).
OIDC optional.
```

| On tip | Not shipped |
|--------|-------------|
| ELv2 source-available (not OSS). Beta, no GA. | Open-source; ready-for-beta testers; unattended merchant beta |
| `make doctor && make demo`. Rust evaluate + receipts + pack-why | Model ALLOW / DENY; Tarka-branded model |
| Observe = canary. Ungated → human Promote. Gates defined+met → may auto-Promote (default off). Human Propose Demote → Confirm. Model never Promotes or demotes. | Live unattended hops; always-on Day-1 auto-Promote; auto-demote |
| Hop packs (`USES_DEVICE` …) `mode=shadow`. Live only after promote gates pass. | Always-on graph; “every evaluate is on the graph”; GNN live |
| Enforcement contract-gated; default emit-only. Outbound webhooks HMAC-SHA256 (`x-tarka-signature`) when secret is set. Empty URL = plane off. Suggested-action `action_id` is hex SHA-256 of tenant + trace_id + action token + pack hash — stable across retries. | Handoff as Day-1 default; silent block in emit-only; unsigned enforcement webhooks as the contract; random `action_id` per POST |
| Empty `GRAPH_SERVICE_URL` = hops off, not sibling identity | Closed omniscient AI author loop; case CRM; consortium SKU |
| L2 leftover/override → Observe draft; AI backtest required first. FP late-label → Observe soften (not CRM) | Beachhead seeds as live; banks as the beachhead |
| Graph-risk / ring-score challenger. Beachhead Observe seeds (promo / COD / payout) stay Observe | Users / LOI / ARR as traction |
| `prod-on-k8s` is core-api HA (external PG/Redis). Generate requires `--digest-map` (`sha256`) for a grade claim. Empty digest is non-grade, not immutable. No sqlite/`emptyDir` for decisions/audit/labels/packs. [production-install-v1](docs/contracts/production-install-v1.md) | GitLab-grade already achieved; GA from preset; mutable tag as the recommended prod pin |
| Community = GitHub issues (no SLA). Commercial pack = VPC / Helm / SSO / pack-GitOps assist + severity intent ([SUPPORT.md](SUPPORT.md)). Grade contract: [production-install-v1](docs/contracts/production-install-v1.md) | 99.99% (or any nines) as a Tarka SLA; SOC 2 from us; hosted Tarka Cloud; GitLab-grade already achieved |

**Docs:** [`docs/INDEX.md`](docs/INDEX.md) · [`SECURITY.md`](SECURITY.md) · [`SUPPORT.md`](SUPPORT.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md)

Community support is GitHub issues. A paid self-host install pack is VPC assist, Helm values review, SSO wiring, pack GitOps export help, and severity response intent — not an uptime percentage. See [`SUPPORT.md`](SUPPORT.md).

Operator CLI (optional): `python3 cli.py` or compose under `infra/deploy/`.

---

## Vision (below the fold)

Manifesto, evaluate-first product lock, Advise / local inference, and entity-state notes live in [`VISION.md`](VISION.md). Day-1 is the compose path above — not a laptop triad and not an enterprise desk.

Graph is on Day-1 (Tarka AGE, or yours). Optional after that: investigation overlay, signals overlay, local Advise/Ollama. Size them from the [SRE compose runbook](docs/docs/operations/sre-compose-profiles.md).

**15-minute first decision** (deeper than `make demo`): [docs/docs/guides/oss-15-minute-first-decision.md](docs/docs/guides/oss-15-minute-first-decision.md) → `python3 scripts/oss/first_decision_smoke.py`

---

## Performance

Reproduce **local** figures only from this README. Hypothetical scale-out projections (if any) live exclusively in [`scripts/benchmarks/README.md`](scripts/benchmarks/README.md) and must never be cited as shipped SLOs.

```bash
python scripts/benchmarks/vertical_benchmark_smoke.py --seed 42 --threshold strict
```

Also see [`latency_evaluate.py`](scripts/benchmarks/latency_evaluate.py). Publish host SKU, compose profile, commit SHA, warm-up count, payload schema.

---

## Repository map

| Path | Role |
|------|------|
| [`frontend/`](frontend/) | React analyst app |
| [`services/`](services/) | Microservices — `core-api` / decision-api, orchestrator, `shadow_agent`, investigation-agent (Observe vs Advise: [`services/SHADOW.md`](services/SHADOW.md)) |
| [`packages/`](packages/) | Internal libs (`deploy-settings`, `shared-core`, SDKs) |
| [`infra/`](infra/) | `infra/deploy/` (Compose, Helm, OPA) + `infra/scripts/` |
| [`docs/`](docs/) | Operator hub [`docs/INDEX.md`](docs/INDEX.md) |
| [`crates/tarka-core/`](crates/tarka-core/) | Rust decision DAG / determinism |
| [`crates/tarka-cli/`](crates/tarka-cli/) | `tarka replay` |

---

## License

Tarka application code is **source-available** under the **Elastic License 2.0**. You may `git clone`, modify, and run Tarka on your own metal or VPC for your own fraud operations. You may not provide Tarka to third parties as a hosted or managed service.

Third-party graph/database runtimes (Apache AGE, Postgres, optional Janus/Neo4j) keep their own licenses — see [`LICENSE-DEPENDENCIES.md`](LICENSE-DEPENDENCIES.md). See [`LICENSE`](LICENSE) for the full ELv2 text.
