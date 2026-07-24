# Removed — use `packages/tarka-rule-engine`

This directory held a **duplicate** Rust PyO3 crate (`tarka_rule_engine`) that was
**excluded** from the Cargo workspace. The canonical wheel lives at:

**`packages/tarka-rule-engine/`**

Do not recreate `services/rule-engine`. Python AST sidecar (legacy) is the
underscore path: `services/rule_engine/` (see its `DEPRECATED.md`).
