# Ease-of-use: three outcomes (Cursor prompts)

> **Do not treat Downloads / Sep packs as the source of truth.** This file is the in-repo prompt pack. Extend existing surfaces. Do not rebuild evaluate, leftovers, Observe, or Hunt.

**Goal:** Demo viewers said Tarka is capable but not easy. Close three gaps, in this order: one-person Day-1, a first hour a non-fraud person can drive, BYO-LLM as a setup step.

**Workspace:** branch `ease/one-person-desk` from current `master` (`#376` `make demo`, `#374` ELv2, `#372` HAS_LIST, `#375` Observe Promote). One logical PR per outcome. Do not commit unless asked.

---

## GLOBAL LOCKS (every prompt)

- Evaluate stays Rust. A model never ALLOW / DENY / REVIEW. A model never Promotes or demotes live.
- Empty `GRAPH_SERVICE_URL` = hops off. No stub neighbors. `graph:missing` when relevant.
- License stays Elastic-2.0. Do not call Tarka OSS or open-source in **new** docs. Keep `scripts/oss/` path names.
- No buyer-demo VO, no ALLOW $42 punchlines, no invented customers or ARR.
- **No named third-party alert or case desks in anything we publish.** README, guides, desk copy, notify titles, OpenAPI, PR titles: Tarka jobs only (receipt, leftover, Observe, Promote).
- Beachhead: last-mile / food / q-comm / gig / store.
- Observe = canary. Humans Promote.
- Leftovers = tune + QA. Do not unhide fat `/cases`. Do not rebuild a case CRM.
- LLM keys only in `.env` / server env. Never in the SPA. Never in localStorage.
- **No parallel path:** cite the existing file first.
- Prefer [ARCHITECTURE.md](../../../ARCHITECTURE.md), [graph_hop_contract.py](../../../services/decision-api/src/decision_api/graph_hop_contract.py), [graph_pack_atoms.py](../../../services/shared/graph_pack_atoms.py), [PACK_AUTHOR.md](../../../services/shadow_agent/PACK_AUTHOR.md), leftover-hunt spec, [feature-data-flows.md](../../docs/guides/feature-data-flows.md), [clone-demo.md](../../docs/guides/clone-demo.md).
- Hand authoring: fill-in-the-blank sentences on `/rules` **only emit the same pack JSON** evaluate already runs. JSON stays the contract. Not a second policy language.
- AI does not mint keys or etypes. Scout / pack-author is allow-listed. Unknown fields dropped. AI contract is flat `when` only — no `graph_v1` / etype emit. Human sentence dropdowns and the AI allow-list read the **same** catalog (canonical counter keys + signed hop etypes for humans). An AI draft never adds a catalog row.
- Velocity: map count / sum / unique_count to existing keys. No `rate` / `baseline_ratio` runtime. No new Rust atom node unless the form cannot emit flat `when` (it can).
- TDD where feasible. CI green. List regression commands in the PR body.

**Explicit non-goals:** consortium SKU, fingerprint SKU, SAR filing, hosted Tarka Cloud, a graph-rule product, a Tarka-branded model, Vertex-as-default, new Redis velocity keys, new MCP scout plane, re-landing `#376`, a no-Docker Day-1, collecting API keys in the browser, a sentence UI that hides evaluate JSON, naming third-party desks.

---

## Outcome 1 — One person clone-and-run

**Issue:** `#376` is one command, but it still fails silently on ports/health and does not print “click this.”

### Prompt P-day1a — `make doctor` then a louder `make demo`

Extend [scripts/oss/up_desk.sh](../../../scripts/oss/up_desk.sh) and [walk_receipts.py](../../../scripts/oss/walk_receipts.py). Do not rewrite walk payloads.

- `make doctor` checks Docker Compose v2, ports `8000` `8001` `3000` `5432` `6379`, and ~4 GB free RAM. Each fail names the fix.
- `up_desk.sh`: abort on health timeout (do not walk a dead API). After PASS, print **one** next line: `NEXT: http://127.0.0.1:3000/…` plus `entity_id`.
- README + [clone-demo.md](../../docs/guides/clone-demo.md): `make doctor && make demo` only. Mac + Linux. No compose-file shopping on Day-1.

**Do not:** new compose stack, Helm, no-Docker path, demo-burst.

**Regressions:** `PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_walk_receipts.py`, `python3 scripts/oss/first_decision_smoke.py` (when the desk is up), `make policy-check`, `make contract-check`. Doctor is host-side and CI-skippable (`infra/scripts/ci/test_doctor.py`).

### Prompt P-day1b — Optional LLM at setup (writes `.env` only)

After doctor, TTY prompt: URL, API key, model. Enter skips. Writes `SHADOW_LLM_BACKEND=vllm` (or `self-hosted`), `SHADOW_LLM_BASE_URL`, `SHADOW_LLM_API_KEY`, `SHADOW_LLM_MODEL` into `infra/deploy/.env`. Non-interactive / CI = skip. Do not use `azure` as a backend name. Keys never go in the browser.

If no thin `shadow_agent` overlay exists, do **not** pull v2-ingest / Ollama / local weights. Record the vars; desk says LLM off until the operator composes Shadow later.

**Regressions:** `PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_setup_llm_env.py`.

---

## Outcome 2 — First hour for someone who is not a fraud native

**Issue:** after the desk is up, a non-fraud person cannot narrate a receipt, leftover, Hunt, pack, or pack performance.

Do this on existing routes. No Command Center. No brochure home.

### Prompt P-hour — Guided jobs (demo / local tenant only)

On each lean page, ≤5 lines, env/flag gated (`FirstHourHint` for `demo`/`local` or `import.meta.env.DEV`):

- `/decisions` — ALLOW means continue (no leftover). REVIEW / DENY means a human should look. Receipt why is the pack, not a model.
- `/leftovers` — work arrives here; work happens on Hunt. Row shows pack id / rule hits from the snapshot. Fail-close if `GET /v1/leftovers` is down. Empty state: REVIEW/DENY mint; ALLOW never.
- `/graph` — Hunt is “who is connected to this person.” Surface `pack_why.graph` / `graph:missing` on the existing [packWhy.ts](../../../frontend/src/utils/packWhy.ts) strip. Do not invent edges.
- `/rules` — sentences **and** form/JSON emit the same Observe pack. FIELD_CATALOG uses canonical keys (`event_count_1h`, `sum_amount_24h`, …). Save = Observe draft. Invalid emit is dropped, not live. Promote stays on `/ops/shadow`.
- `/analytics/rule-performance` — English: which packs fired, which look noisy. Link open pack → `/rules`, Promote → `/ops/shadow`.
- `/ops/shadow` — Observe is a canary. Live packs still decide. A model never ALLOW/DENY. If `is_ai_authored`: model drafted — you own live.

**Supporting:** [velocity-atoms.md](../../docs/guides/velocity-atoms.md), [hop-pack-authoring.md](../../docs/guides/hop-pack-authoring.md). No fourth hop pack. No `rate` / `baseline_ratio`.

**Regressions:** leftover row unit tests, `packWhy.test.ts`, `sentencePack.test.ts`, `FirstHourHint.test.ts`, `Leftovers.test.tsx`.

---

## Outcome 3 — BYO-LLM is a setup step, not a second project

**Issue:** pointing a model at Tarka is a README paragraph. Demo viewers never reach `publish_scout_pack`. The host loop already exists — tell it on the desk.

### How it already works (do not rebuild)

1. Scout (LLM or deterministic template) POSTs `create_scout_pack`. `mode` is always `shadow`. `is_ai_authored=true`. Invalid JSON is dropped. Model cannot Promote.
2. Ready to Promote = `/ops/shadow` gates (`desk_promote_gate.promote_allowed`). Human clicks Promote.
3. Live-rule drift is the host **live-rule slip** critic, not the BYO LLM. Advise/LLM off still pings.
4. H1 park retire draft / H2 park successor draft. Live stays `active`. Promote of a slip draft **adds** a file; it does **not** strip the live rule. Demote live is a human `PUT`. Scout that would clobber a slip draft → `409 slip_draft_exists`.

### Prompt P-byom — Connect at setup, make the loop obvious on `/ops/shadow`

- Setup: P-day1b. Skip = plane off.
- Later: same four vars in `.env` / compose; restart `shadow_agent`. One recipe in clone-demo. Do not conflate Advise `OPENAI_BASE_URL`.
- Desk (no secrets): LLM **connected / off**. **Test** = backend ping. **Draft Observe pack** = existing `POST /v1/rules/scout-pack`.
- Three English cards from `GET /v1/calibration/shadow-promote-gate`:
  - **Ready to Promote** — drafts whose gates pass; one sentence why.
  - **Not yet** — drafts blocked; name the blocker.
  - **Live rule slipped** — H1 “consider taking this live rule back to Observe” / H2 “consider this successor in Observe.” Buttons: open draft, human Promote, human demote (existing PUT). Copy: the model did not turn live off.

### Prompt P-notify — one event list, two sinks

Same events, English body, no second drift engine.

| Event | When |
| Ready to Promote | `desk_promote_gate.promote_allowed` flips true for a draft |
| Live rule slipped (ping) | `live_rule_slip` names a `rule_id` and does not park |
| Consider demote (H1) | retire draft parked |
| Consider successor (H2) | successor draft parked |

- Store: append-only notify rows on decision-api (tenant, type, English `title`/`body`, `href` to `/ops/shadow` or draft id, created_at, read_at). Dedupe `(tenant, type, draft_id or rule_id)`.
- Desk: `/notifications` is a lean-nav list + unread mark. Same English as `/ops/shadow`. Click opens the draft. Not a leftover queue.
- Webhook: `TARKA_OBSERVE_NOTIFY_WEBHOOK_URL` + optional secret — same pattern as `TARKA_ENFORCEMENT_WEBHOOK_URL`. Envelope `tarka.observe_notify/v1`. Empty URL = desk-only. Fail-soft: webhook 5xx does not block evaluate or Promote. GET `shadow-promote-gate` and Observe evaluate must **not** write notify rows.

**Tests:** empty LLM URL = zero remote scout calls; slip still works with LLM off; empty notify URL = no POST; promote-ready only when gates pass; invalid pack dropped; no live publish; Promote does not strip live `rule_id`; `409 slip_draft_exists` unchanged; no auto-Promote/demote from a notify click.

**Do not:** let the LLM demote or Promote; auto-demote live; first-party Slack/email SKU; `replaces_rule_id` this month; MCP skill folders; keys in the SPA; Vertex default; Advise conflation; a second drift engine.

---

## Definition of done

- One person with Docker Desktop: `make doctor && make demo` → PASS or a named fix → one printed click.
- A non-fraud viewer can use evaluate output, leftovers, Hunt, create an Observe pack from `/rules` (sentence or JSON — same pack), and read pack performance in English.
- BYO-LLM: asked at setup, skippable, addable later via backend; desk shows connected/off + Test + Draft; keys never in the browser; Promote still human.
- Ready-to-Promote and live-rule slip emit English notify rows: desk `/notifications` plus optional webhook. Model still never Promotes or demotes.
- Master CI green. ELv2 unchanged.

## Regression commands (PR body)

```bash
PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_doctor.py
PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_setup_llm_env.py
PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_walk_receipts.py
cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_observe_notify.py tests/test_live_rule_slip.py tests/test_live_rule_slip_api.py tests/test_shadow_promote_gate_api.py tests/test_decision_outcome.py -q
cd frontend && npm test -- --run src/utils/packWhy.test.ts src/utils/sentencePack.test.ts src/components/FirstHourHint.test.ts src/pages/Leftovers.test.tsx src/config/leanNav.test.ts src/domain/liveRuleSlip.test.ts
make policy-check
make contract-check
```
