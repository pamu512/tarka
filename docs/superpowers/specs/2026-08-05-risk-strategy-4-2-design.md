# Risk / Strategy 4.2 — strategy honesty stack (path to 4.5)

**Date:** 2026-08-05  
**Branch:** `maturity-4-0-local`  
**Status:** Approved design (Approach 1 / option B+C)  
**Bar:** Critical / skeptical — no live vendor this pass; location stays externally gated

## Goal

Move **Risk / Strategy** from ~**3.6** to **4.2** under critical rules **without** a live named-tenant partner pin this pass. Reserve **4.5** for when `partner-fusion-proof.live.sha256` + named tenant land on top of this stack. Location six-cap remains **~2.9–3.2** (L1 fixture only). Do not claim product-wide 4.2 from this work alone.

## Problem

| Gap | Today | Needed for 4.2 (no L2 data) |
| --- | ----- | --------------------------- |
| Live partner | L1 fixture pin; L2 optional/waiver prose | Fail-closed LIVE\|WAIVED machine contract in CI |
| Promote safety | kill_criteria on vertical promote + smoke | Named CI gate; no skippable promote path |
| Diligence pack | Docs + partial evidence index | Index requires L2 status + promote proof paths |

## Approach

**Strategy honesty stack**

1. Fail-closed live-proof CI contract (`REQUIRE_LIVE_PARTNER_PROOF=1` satisfied by LIVE pin **or** `WAIVED` line — never by fixture alone)  
2. Harden/verify kill_criteria promote/deploy gate in CI  
3. Machine-checkable diligence evidence index  
4. Regrade Risk/Strategy to **4.2**; aim footnote for **4.5** = L2 live pin + this stack  

## Non-goals

- Inventing live vendor traffic or copying fixture SHA into `.live.sha256`  
- Native Incognia / device network  
- Claiming location ≥4.0 or Risk **4.5** this pass  
- Inflating Engineering/Ops scores  

## Design

### 1. Live-proof status contract

**File:** `docs/compliance/partner-fusion-proof.live.status`

Exact formats (one line, trimmed):

- `LIVE` — requires `docs/compliance/partner-fusion-proof.live.sha256` to exist and be non-empty  
- `WAIVED — reason: <non-empty text>` — allowed when live vendor unavailable  

**Script:** extend `scripts/oss/partner_fusion_tenant_proof.py` or add `scripts/oss/partner_fusion_live_status_gate.py`:

- Default CI: L1 fixture unchanged  
- When `REQUIRE_LIVE_PARTNER_PROOF=1`: exit 0 only if LIVE+sha present **or** valid WAIVED line; exit 1 if status missing, fixture used as live, or LIVE without sha  

**CI:** add step in honesty job of `.github/workflows/ci.yml` with `REQUIRE_LIVE_PARTNER_PROOF=1` reading the status file (OSS default: commit `WAIVED — reason: no live vendor credentials in OSS CI`).

### 2. kill_criteria hard promote gate

- Keep/extend `POST /v1/rules/vertical-packs/{vertical_name}/promote` conflict when kill fires.  
- Ensure `tests/test_kill_criteria_promote_gate.py` is in decision-api CI (already via pytest suite).  
- If any sibling activate/deploy path skips the gate, add the same check.  
- Document in evidence index path.

### 3. Diligence evidence index

Expand `scripts/compliance/export_control_evidence_index.py` `_PATHS` to include at least:

- `docs/compliance/partner-fusion-proof-runbook.md`  
- `docs/compliance/partner-fusion-proof.stable.sha256`  
- `docs/compliance/partner-fusion-proof.live.status`  
- `services/decision-api/tests/test_kill_criteria_promote_gate.py`  
- `docs/compliance/customer-control-evidence-pack.md`  

CI: run exporter; fail if `missing` non-empty.

### 4. Regrade

After gates green:

- Risk/Strategy **4.2** on canvas + matrix  
- Location still **~2.9** / “fixture L1; L2 WAIVED or pending”  
- Aim **4.5** when LIVE pin replaces WAIVED  

## Acceptance

Risk/Strategy **≥4.2** iff:

1. Live-status gate green under `REQUIRE_LIVE_PARTNER_PROOF=1`  
2. kill_criteria promote conflict proven in CI tests  
3. Control evidence index has zero missing required paths  
4. Regrade explicitly does **not** claim location 4.0+ or Risk 4.5  

## Path to 4.5

Replace `WAIVED` with `LIVE` + committed `.live.sha256` from named tenant; keep promote gate + evidence index. Regrade Risk/Strategy to **4.5** and location toward **≥4.0** hybrid floor.

## Open questions (resolved)

- Earn vs claim: **Earn**  
- Live vendor: **None this pass** → WAIVED + fail-closed path  
- Scope: live status CI + kill promote gate + evidence index (**C**)
