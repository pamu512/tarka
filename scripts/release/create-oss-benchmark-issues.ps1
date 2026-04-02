# One-off: create 12 borrowed-from-OSS issues and map to module swimlanes project.
# Requires: gh auth, repo pamu512/tarka, project "Tarka Module Swimlanes" (#3)
$ErrorActionPreference = "Stop"
$repo = "pamu512/tarka"
$projectNumber = 3
$owner = "pamu512"
$projectId = "PVT_kwHODeOS184BTflm"
$fieldId = "PVTSSF_lAHODeOS184BTflmzhAuMqA"
# Module option ids (single-select on project)
$mod = @{
  "Decision API"         = "f76dd42a"
  "Case API"             = "6fb14b21"
  "Graph Service"        = "20705585"
  "ML Scoring"           = "08877c35"
  "Feature Service"      = "3cc8c612"
  "Integration Ingress"  = "4593e9e0"
  "Frontend"             = "7038f823"
  "SDK Python"           = "6541678b"
  "SDK TypeScript"       = "93698a7c"
  "SDK Mobile"           = "3378e494"
  "Analytics Sink"       = "00c7f3aa"
  "Investigation Agent"  = "a340ce95"
}

$items = @(
  @{
    Module = "Decision API"
    Title  = "Policy DAG: canary, shadow, and champion-challenger routing"
    Body   = @"
## Module swimlane
**Decision API**

## borrowed-from-OSS
**Pattern:** Orchestrated decision DAG with production-safe experimentation.

**Source:** [zhucl121/risk-engine](https://github.com/zhucl121/risk-engine) — YAML ``PolicySet`` with hash-stable canary, random A/B, shadow dry-run (``shadow_audit``), champion-challenger (``cc_audit`` + agreement), and routing priority.

## Scope
- Add a policy orchestration layer in the decision path: main pipeline + optional canary branch + parallel shadow/CC evaluation.
- Persist shadow and CC outcomes for offline analysis without changing production allow/deny/review for shadow.
- Document hash key + salt semantics for stable cohort routing.

## Acceptance criteria
- [ ] Canary: configurable traffic % and stable bucket per entity key.
- [ ] Shadow: never mutates production decision; outcomes queryable/exportable.
- [ ] CC: champion returned to client; challenger + agreement stored for promotion analysis.
- [ ] Integration tests cover routing priority (canary > AB > main) or documented Tarka equivalent.

## Reference
risk-engine README: Policy Configuration + Routing priority table.
"@
  }
  @{
    Module = "Decision API"
    Title  = "Pipeline step controls: timeouts, retries, and onFailure semantics"
    Body   = @"
## Module swimlane
**Decision API**

## borrowed-from-OSS
**Pattern:** Per-step resilience in a DAG decision pipeline.

**Source:** [zhucl121/risk-engine](https://github.com/zhucl121/risk-engine) — per-step ``timeoutMs``, ``retry`` (maxAttempts + delayMs), ``onFailure`` (SKIP / REJECT / FALLBACK), and conditional step skip via DSL ``condition``.

## Scope
- Map enrichment steps (lists, rules, ML, graph, integrations) to explicit step metadata.
- Standardize fail-open vs fail-closed per step class with tenant-safe defaults.
- Emit structured audit for skipped/failed steps.

## Acceptance criteria
- [ ] Step timeouts enforced; no unbounded waits on optional enrichers.
- [ ] Retry policy configurable for flaky IO (with caps and jitter optional).
- [ ] onFailure behavior documented and tested for at least list, model, and graph steps.
- [ ] Metrics: step latency, timeout count, failure reason codes.

## Reference
risk-engine README: Pipeline step controls + Policy Configuration examples.
"@
  }
  @{
    Module = "Feature Service"
    Title  = "Velocity counters: atomic sliding windows and online/offline parity checks"
    Body   = @"
## Module swimlane
**Feature Service**

## borrowed-from-OSS
**Pattern:** High-performance sliding-window counters with explicit windows.

**Source:** [zhucl121/risk-engine](https://github.com/zhucl121/risk-engine) — Redis Lua atomic sliding-window counters (1m / 1h / 24h), ``velocity()`` in RiskDSL, optional standalone feature store gRPC.

## Scope
- Ensure 5m/1h/24h (or 1m/1h/24h) counter keys are atomic and documented.
- Add replay/compare job: live counter vs replayed history within tolerance.
- Expose normalized feature keys for rules and ML (align with Epic C).

## Acceptance criteria
- [ ] Counter increments and reads are race-safe under load.
- [ ] Parity test: replayed window matches live within defined epsilon for fixture dataset.
- [ ] Keys versioned and documented in OpenAPI/rule docs.

## Reference
risk-engine README: Features (Velocity counters) + Feature Store section.
"@
  }
  @{
    Module = "Decision API"
    Title  = "Typology layer: aggregate rule outcomes into scored scenarios with thresholds"
    Body   = @"
## Module swimlane
**Decision API**

## borrowed-from-OSS
**Pattern:** Rules feed typologies; typologies aggregate evidence before final action.

**Source:** [tazama-lf/docs](https://github.com/tazama-lf/docs) — Event Director routes to rule processors; Typology Processor aggregates rule outputs per typology config; thresholds drive alert vs interdict vs pass.

## Scope
- Introduce typology definitions (config): member rules, weights/predicates, breach thresholds.
- Map typology breach levels to Tarka actions (allow / review / deny / challenge hook).
- Persist per-typology score breakdown in audit for analysts.

## Acceptance criteria
- [ ] At least 3 reference typologies ship with tests (e.g. velocity + new payee + amount).
- [ ] Rule outcomes reused across typologies without duplicate computation where possible.
- [ ] Audit shows typology id, score, contributing rules, and final disposition.

## Reference
Tazama docs: sections 2–3 (typologies and rule processors) and Typology Processor overview.
"@
  }
  @{
    Module = "Case API"
    Title  = "Investigation workflows: templates, annotations, and action history export"
    Body   = @"
## Module swimlane
**Case API**

## borrowed-from-OSS
**Pattern:** Unified case investigation with audit-friendly activity.

**Source:** [checkmarble/marble](https://github.com/checkmarble/marble) — investigation suite, annotations, workflow actions, searchable audit trail positioning.

## Scope
- Case templates per alert typology or risk tier (fields, checklists, SLA hints).
- Structured annotation and action log with export (JSON) for external ticketing.
- API for attaching decision/graph evidence snapshots to a case revision.

## Acceptance criteria
- [ ] Template CRUD + assign template on case create from decision webhook path.
- [ ] Action history immutable append with actor + timestamp + payload hash optional.
- [ ] Export bundle includes trace ids, typology/rule refs, and case timeline.

## Reference
Marble README: Investigation suite + Audit Trail features.
"@
  }
  @{
    Module = "Frontend"
    Title  = "UX for evaluation posture: detection vs compliance modes and degraded states"
    Body   = @"
## Module swimlane
**Frontend**

## borrowed-from-OSS
**Pattern:** Explicit runtime mode and health semantics for operators.

**Source:** [opensource-finance/osprey](https://github.com/opensource-finance/osprey) — ``detection`` vs ``compliance`` modes; compliance degraded when typologies missing; ``/health`` vs ``/ready`` behavior.

## Scope
- Surface tenant/system evaluation mode and required dependencies (e.g. typologies loaded).
- Show degraded banner when compliance prerequisites missing; link to runbook.
- Align with Tarka backend flags when introduced.

## Acceptance criteria
- [ ] Trust/ops panel shows mode, dependency status, and last config reload time if available.
- [ ] E2E or integration test with mock API for degraded compliance state.
- [ ] Copy reviewed for analyst vs admin audiences.

## Reference
Osprey README: Evaluation Modes + API Endpoints (health/ready).
"@
  }
  @{
    Module = "ML Scoring"
    Title  = "Model promotion gates: block rollout on challenger vs champion regression"
    Body   = @"
## Module swimlane
**ML Scoring**

## borrowed-from-OSS
**Pattern:** Champion-challenger with statistical guardrails before promotion.

**Source:** [zhucl121/risk-engine](https://github.com/zhucl121/risk-engine) — parallel challenger evaluation, ``cc_audit``, agreement flag; combined with explicit canary traffic increase.

## Scope
- Define promotion policy: max FP rate delta, min recall/lift on golden set, latency SLO.
- CI or scheduled job compares champion vs challenger on fixed benchmark dataset.
- Registry integration: promotion requires passing gate artifact (signed report optional later).

## Acceptance criteria
- [ ] Gate config lives in repo or config service with version id.
- [ ] Failed gate blocks ``approved`` → ``active`` transition without override role.
- [ ] Report artifact stored and linked from release notes or internal URL field.

## Reference
risk-engine README: championChallenger + Performance tables.
"@
  }
  @{
    Module = "Integration Ingress"
    Title  = "Deployment profiles: community vs pro tier (compose/env documentation)"
    Body   = @"
## Module swimlane
**Integration Ingress**

## borrowed-from-OSS
**Pattern:** Tiered runtime for fast onboarding vs production footprint.

**Source:** [opensource-finance/osprey](https://github.com/opensource-finance/osprey) — Community (SQLite + in-memory + channels) vs Pro (Postgres + Redis + NATS).

## Scope
- Document and ship compose overlays: ``community`` (minimal deps) vs ``pro`` (full stack).
- Env matrix table: DB, cache, bus, feature flags per tier.
- Validate integration-ingress and decision paths on both tiers in CI smoke (optional nightly).

## Acceptance criteria
- [ ] Single doc page with copy-paste commands for each tier.
- [ ] ``.env.example`` fragments per tier or documented substitutions.
- [ ] Known limitations listed per tier (e.g. no horizontal scale on community).

## Reference
Osprey README: Runtime Profiles + Configuration table.
"@
  }
  @{
    Module = "Decision API"
    Title  = "Starter typology packs with versioned fixtures and CI smoke"
    Body   = @"
## Module swimlane
**Decision API** (packs live under ``rules/`` / ``deploy`` / ``tests/fixtures`` as appropriate)

## borrowed-from-OSS
**Pattern:** Starter kit rules/typologies for immediate value.

**Source:** [opensource-finance/osprey](https://github.com/opensource-finance/osprey) — ``seed-starter-kit.sh``; [tazama-lf/docs](https://github.com/tazama-lf/docs) — typology philosophy and examples.

## Scope
- Ship 1–2 starter packs (e.g. payments + ATO-lite) as versioned YAML/JSON.
- Fixture transactions/events with expected typology outcomes for CI.
- Wire into simulation or decision-api test harness.

## Acceptance criteria
- [ ] ``make test`` or CI job loads packs and asserts golden outcomes.
- [ ] README section: how to enable/disable packs per tenant.
- [ ] Changelog entry template for pack semver bumps.

## Reference
Osprey docs: STARTER_KIT; Tazama docs: typology examples.
"@
  }
  @{
    Module = "Investigation Agent"
    Title  = "Evidence summaries and next-best-action keyed by typology and rule drivers"
    Body   = @"
## Module swimlane
**Investigation Agent**

## borrowed-from-OSS
**Pattern:** Analyst assist grounded in explicit rule/typology contributions.

**Source:** [tazama-lf/docs](https://github.com/tazama-lf/docs) — typology scoring explains contributing rules; [checkmarble/marble](https://github.com/checkmarble/marble) — AI assistance in investigation positioning.

## Scope
- Input: case id + latest decision audit + typology breakdown + graph excerpt.
- Output: short summary, cited bullet list (trace/rule/typology ids), suggested next actions with confidence labels.
- Deterministic mode for tests (fixed seed / template expansion).

## Acceptance criteria
- [ ] API returns citations that resolve to stored artifacts or ids.
- [ ] No action without policy allow-list for automated side effects.
- [ ] Golden-file tests for 3 fixture cases.

## Reference
Tazama Typology Processor narrative; Marble investigation + AI assistance features.
"@
  }
  @{
    Module = "Analytics Sink"
    Title  = "Automated release scorecards: precision, latency, FP-cost, rollback hooks"
    Body   = @"
## Module swimlane
**Analytics Sink**

## borrowed-from-OSS
**Pattern:** Operational analytics + experiment audit streams for program performance.

**Source:** [checkmarble/marble](https://github.com/checkmarble/marble) — embedded analytics / BI framing; [zhucl121/risk-engine](https://github.com/zhucl121/risk-engine) — Prometheus metrics, shadow/cc audit channels.

## Scope
- Nightly or on-tag job: export metrics + benchmark results to single scorecard artifact.
- Dashboards or markdown report: latency percentiles, rule hit rates, FP proxy, drift vs baseline.
- Optional webhook to annotate GitHub release or discussion.

## Acceptance criteria
- [ ] Scorecard generated from fixed seed in CI (deterministic subset).
- [ ] Fields: build id, dataset version, champion vs shadow delta summary.
- [ ] Documented rollback criterion (e.g. FP delta > X bps fails gate).

## Reference
Marble README: Reporting & BI; risk-engine observability + audit sections.
"@
  }
  @{
    Module = "Graph Service"
    Title  = "Selective evaluation routing: which graph features run per checkpoint (event-director pattern)"
    Body   = @"
## Module swimlane
**Graph Service**

## borrowed-from-OSS
**Pattern:** Route events through a configurable map to only required processors.

**Source:** [tazama-lf/docs](https://github.com/tazama-lf/docs) — Event Director + network map decides which rules/typologies apply; avoids redundant work.

## Scope
- Checkpoint → enabled graph query profile (e.g. payment vs login vs payout).
- Config map in DB or YAML with hot-reload story aligned with decision-api.
- Metrics: skipped vs executed graph queries per request.

## Acceptance criteria
- [ ] Default map covers core checkpoints; unknown checkpoint uses safe minimal graph read.
- [ ] Integration test: same event with two profiles produces different graph feature sets.
- [ ] Document how analysts add a new checkpoint without code deploy (if supported).

## Reference
Tazama docs: Event Director + core components diagram.
"@
  }
)

foreach ($it in $items) {
  $tmp = New-TemporaryFile
  Set-Content -Path $tmp -Value $it.Body -Encoding utf8
  # gh issue create prints the issue URL on stdout (no --json on older gh)
  $url = (gh issue create --repo $repo --title $it.Title --body-file $tmp --label "borrowed-from-OSS").Trim()
  Remove-Item $tmp -Force
  if ($url -notmatch '^https://') { throw "issue create failed or returned unexpected output: $url" }
  $item = gh project item-add $projectNumber --owner $owner --url $url --format json | ConvertFrom-Json
  $opt = $mod[$it.Module]
  if (-not $opt) { throw "Missing module mapping for $($it.Module)" }
  gh project item-edit --id $item.id --project-id $projectId --field-id $fieldId --single-select-option-id $opt | Out-Null
  Write-Output "Created + mapped: $url -> $($it.Module)"
}
