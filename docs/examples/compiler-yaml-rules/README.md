# Compiler YAML rule examples

These files use the **Rust engine YAML schema** (`version`, `rules[].id`, `rules[].expression` with `kind: and|or|not|compare_signal`). They are scanned by:

- `scripts/docs/generate_rule_logic_docs.py` — MkDocs **Logic reference** pages
- Management service `/signals/impact` when `TARKA_MANAGEMENT_YAML_RULES_ROOT` points at a tree containing the same format

Decision API **JSON** packs (`services/decision-api/rules/*.json`) are a different format; see the Rule Authoring guide.
