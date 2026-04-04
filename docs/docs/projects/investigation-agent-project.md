# Investigation Agent Project

## Scope

Workflow assistant capabilities for case triage, evidence gathering, and analyst productivity.

## Current Gaps

- LLM narratives are not mechanically verified; tool JSON truncation and wrong tool choice remain risks.
- Recommendation confidence and policy-safe automation are early-stage (copilot is read-mostly; label drafts are separate from case workflow labels).
- Deep integration with **evidence bundle schema** (#50) and benchmark scorecards is still limited.

**Shipped in tree (keep docs in sync):** tool loop to case-api (cases, disputes), graph, decision-api (audit, entity-velocity, replay); **paired replay** via `trace_ids`; **durable label drafts** via `/v1/investigation-label-drafts`; export of weak labels from cases/disputes; **tool-quality** metrics + structured logs per chat.

## Roadmap

### Now

- Align agent output shapes with **evidence bundle v1** when schema lands; extend deterministic traces for analyst trust.
- Add guardrails for action suggestions and policy-safe defaults.

### Next

- Add case pattern recall and escalation quality feedback loops.
- Integrate richer evidence packaging into review workflows.

### Later

- Semi-autonomous triage playbooks with strict human-in-the-loop boundaries.
