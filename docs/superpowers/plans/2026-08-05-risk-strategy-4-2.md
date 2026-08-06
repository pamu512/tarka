# Risk / Strategy 4.2 Implementation Plan

> **For agentic workers:** Use executing-plans or SDD. Checkboxes track progress.

**Goal:** Earn critical Risk/Strategy 4.2 via fail-closed live-proof status, kill_criteria promote CI proof, diligence evidence index — path to 4.5 when L2 live pin lands.

**Spec:** `docs/superpowers/specs/2026-08-05-risk-strategy-4-2-design.md`

## Global Constraints

- No fake `.live.sha256` from fixture digest  
- Location six-cap stays &lt;4.0 this pass  
- Do not claim Risk 4.5 until LIVE pin  
- Score bump only after gates green  

---

### Task 1: Live status file + gate script + CI

- Create: `docs/compliance/partner-fusion-proof.live.status` with  
  `WAIVED — reason: no live vendor credentials in OSS CI`  
- Create: `scripts/oss/partner_fusion_live_status_gate.py`  
  - Reads status file  
  - `REQUIRE_LIVE_PARTNER_PROOF=1` → exit 0 on valid WAIVED or LIVE+sha; else 1  
  - Without env flag → exit 0 after validating format if file present  
- Add CI step after partner fusion fixture proof  
- Self-test: stdlib unittest with temp LIVE missing sha fails; WAIVED passes  

### Task 2: Verify kill_criteria promote in CI narrative

- Confirm `test_kill_criteria_promote_gate.py` covers promote conflict  
- If activate/deploy sibling skips gate, add check  
- Add path to evidence index  

### Task 3: Expand evidence index + CI

- Update `scripts/compliance/export_control_evidence_index.py` `_PATHS`  
- CI: `python3 scripts/compliance/export_control_evidence_index.py` must exit 0  

### Task 4: Regrade after green

- Canvas + matrix: Risk/Strategy **4.2**; location still fixture; aim 4.5 = LIVE  
- Honesty program bullet  
