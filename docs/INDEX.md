# Tarka documentation hub

Canonical operator docs.

## Audiences

| Audience | Start here |
|----------|------------|
| **Clone and run** — desk + real receipts | [`make demo`](docs/guides/clone-demo.md) |
| **Product Day-1** — `make product` + Helm `desk_provision` | [product Day-1 install](docs/guides/product-day1-install.md) |
| **Strategy analyst** — author and promote packs (JSON rules) | [clone-and-run desk](docs/guides/clone-demo.md) · [15-minute first decision](docs/guides/oss-15-minute-first-decision.md) · [Quickstart](docs/quickstart.md) · [Rule authoring](docs/guides/rules.md) · [Observe / promote](docs/guides/shadow-and-ab-testing.md) · [Backtest before promote](docs/guides/backtest-before-promote.md) |
| **Investigator** — work the Person on Hunt; leftovers are the thin station | [clone-and-run desk](docs/guides/clone-demo.md) · [15-minute first decision](docs/guides/oss-15-minute-first-decision.md) · [Feature data flows](docs/guides/feature-data-flows.md) |
| **Buyer / LOI** — what the self-host install pack is (and is not) | [SUPPORT.md](../SUPPORT.md) · [CLAIM_LOCK](compliance/CLAIM_LOCK.md) · [buyer pilot assessment](compliance/2026-09-08-buyer-pilot-assessment.md) |

Investigators do not author rules; strategy analysts do. Work **arrives** on `/leftovers`. Work **happens** on Hunt (`/graph`). Fat `/cases` stays hidden in lean. ALLOW never becomes a leftover.

## Topics

| Topic | Start here |
|-------|------------|
| **Evaluate (decision stream)** | [Feature data flows](docs/guides/feature-data-flows.md) · [architecture](docs/architecture.md) · [decision-api](../services/decision-api/README.md) |
| **Graph / Hunt (required for the desk)** | Lite Day-1 is Apache AGE on the same Postgres + `graph-service`. Wire another graph with `GRAPH_SERVICE_URL` + `GRAPH_BACKEND`. Empty URL is evaluate-only fallback (home `/decisions`) — hops off, **not sibling identity**, not always-on graph. Evaluate never waits on graph. [hop packs](docs/guides/hop-pack-authoring.md) · [graph-risk challenger](docs/guides/gnn-label-loop.md) · [service-ports](docs/guides/service-ports.md) |
| **Leftovers** | Thin station `GET /v1/leftovers` + desk `/leftovers`. Hold / resolve stay on Hunt. |
| **Observe** | Pack canary + leftover promote + live-rule slip on `/ops/shadow` (always-on lean). RFP "shadow mode" = Observe evaluate (`metadata.shadow`) only — not the LLM. [Shadow / A/B guide](docs/guides/shadow-and-ab-testing.md). |
| **Advise (optional)** | [services/SHADOW.md](../services/SHADOW.md) · Shadow agent LLM · BYO OpenAI-compat URL (Gemini / Claude / Qwen / vLLM presets). Named `azure` / `vertex` / `bedrock` backends refuse — use `self-hosted` + URL. Empty URL = off. No Tarka-branded model. |
| **Cases (residual / SAR)** | case-api + [feature data flows §3](docs/guides/feature-data-flows.md#3-leftovers-hunt-brief-sar). Leftover list is not fat `/cases`. |
| **Deploy / SRE** | [SRE Compose profiles](docs/operations/sre-compose-profiles.md) · [deployment / Helm OIDC](docs/guides/deployment.md) · [quickstart](docs/quickstart.md) · [productionization](docs/guides/repo-productionization-runbook.md) · [secrets matrix](contracts/production-install-v1.md) · [secrets rotation](docs/guides/production-secrets-rotation.md) · [production observability](docs/guides/production-observability.md) · [production backup / restore](docs/guides/production-backup-restore.md) · [production upgrade / rollback](docs/guides/production-upgrade.md) · [production install soak checklist](docs/guides/production-install-soak-checklist.md) (G9; grade gated) |
| **MkDocs site** | `docs/docs/` + `docs/mkdocs.yml` (`mkdocs serve` from `docs/`) |

## QA: two separate loops

1. **Blind predetermined-N evaluate events** — HIL confirms the engine. Schedulable; skip only if no drift.
2. **Second-human sample of cases already closed by HIL** — existing `qa_sample_closed_cases` / `/ops/qa`.

Do not collapse them into one workflow. Do not invent review rates.

## Tip honesty

| True | Not shipped |
|------|-------------|
| ELv2 source-available. Beta, no GA. `make doctor && make demo` | OSS; ready-for-beta testers; unattended merchant beta |
| Observe ≠ live until promote gates pass. Ungated → human Promote. Gates defined+met → may auto-Promote (default off). Model never Promotes or demotes. | Live unattended hops; always-on Day-1 auto-Promote; auto-demote; GNN live; always-on graph |
| Enforcement contract-gated; default emit-only | Handoff as Day-1 default |
| Empty `GRAPH_SERVICE_URL` = hops off, not sibling identity | Omniscient AI author loop; model ALLOW/DENY; case CRM; consortium SKU |
| L2 leftover/override → Observe draft (AI backtest required). FP late-label → Observe soften. Beachhead seeds stay Observe | Beachhead = banks; seeds = live |
| `prod-on-k8s` is core-api HA (external PG/Redis). `--digest-map` required for a grade claim. Empty digest is non-grade, not immutable. No sqlite/`emptyDir` for decisions/audit/labels/packs. [production-install-v1](contracts/production-install-v1.md) | GitLab-grade already achieved; GA from preset; mutable tag as the recommended prod pin |
| Prod examples use secret refs. Empty `API_KEYS` + empty OIDC + insecure off → 503 | Vault required; open evaluate when secrets missing; GitLab-grade already achieved |
| Community = GitHub issues (no SLA). Commercial pack = VPC / Helm / SSO / pack-GitOps assist + severity intent ([SUPPORT.md](../SUPPORT.md)). Grade: [production-install-v1](contracts/production-install-v1.md) | 99.99% SLA; SOC 2 from us; hosted Tarka Cloud; GitLab-grade already achieved |
| Soak checklist exists (G9). GitLab-grade only after G0–G8 **and** a named-pilot sign-off. Not primary decisioner. | GitLab-grade already achieved; SOC 2 from us; GA from `prod-on-k8s` |

## Product locks

- **Skip does not block.** Skipping or avoiding a risk check raises showing-signs risk; it does not hard-block.
- **Entity states** — proven / already-risky · showing-signs · unknown. Device is a node, not the person. ATO victims stay good.
- **Visual rule builder** is a product-desk job, not stretch. JSON packs still decide. `make demo` stays first-hour lean; the product image shows visual / backtest / lists. Stretch is Command Center / brochure, not the canvas.
- **No Tarka-branded model.** Advise is BYO LLM.

## Compose (one story)

```bash
make demo
```

That is the Day-1 path (Lite + fraud-desk + honest evaluate walk). Same as the README. [clone-and-run desk](docs/guides/clone-demo.md). Compose-only: `docker compose -f infra/deploy/docker-compose.lite.yml -f infra/deploy/docker-compose.fraud-desk.yml up --build`. Investigation / signals / Janus overlay: [SRE compose profiles](docs/operations/sre-compose-profiles.md). Lab files (`v2-ingest`, graph-wire) live under `infra/deploy/archive/`.
