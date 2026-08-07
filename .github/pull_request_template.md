## Summary

<!-- What changed, why, and any risk notes for reviewers. -->

## Type of change

- [ ] Bug fix
- [ ] Feature / enhancement
- [ ] Documentation or developer tooling only
- [ ] Refactor (intended no behavior change)

## Review checklist

- [ ] Has tests?
- [ ] Passes Ruff?
- [ ] Updates AuditLog schema?
- [ ] Partner fusion: fixture SHA still pinned **or** live tenant proof SHA attached **or** waiver noted (`docs/compliance/partner-fusion-proof-runbook.md`)
- [ ] If touching `/ops/qa` or QA sampling APIs: confirm Ops QA desk e2e workflow is green on schedule/dispatch (`.github/workflows/ops-qa-desk-e2e.yml`)

If AuditLog schema is not applicable, write **`AuditLog schema: N/A`** in the Summary above (no migration or ORM change to audit tables).

### Release / deal-room partner proof

For release tags or customer diligence packs, attach **live** partner-fusion proof SHA **or** write an explicit waiver:

`Partner live proof: WAIVED — reason: <…> — fixture pin 3d1ab910… still required in CI`

## Rule engine / AST (read carefully)

Pull requests that **break or make nondeterministic** the **JSON rule AST** evaluation path—operator semantics, ordered evaluation of `when_ast`, leaf operator parity with documented contracts, or materialized rules used for production decisions—**will be rejected** unless accompanied by an explicit maintainer-approved spec change and full regression coverage.

---

<!-- Keep links or issue references below. -->
**Related:** <!-- e.g. Fixes #123 -->
