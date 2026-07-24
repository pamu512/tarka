# Task 5 Report

## Summary

Implemented a focused OKF retrieval module that performs exact registry resolution, bounded link expansion, and hybrid RAG fallback with authority ranking, stale indexed-hash rejection, conflict detection, and abstention signaling. Exported an async facade from `knowledge_store.py` so later tasks can reuse the existing `search_async` embedding/keyword fallback boundary.

## Files Changed

- `services/investigation-agent/src/investigation_agent/okf_retrieval.py`
- `services/investigation-agent/src/investigation_agent/knowledge_store.py`
- `services/investigation-agent/tests/test_okf_retrieval.py`
- `services/investigation-agent/resources/okf_retrieval_corpus_v1.json`

## Exact Commands and Results

### Environment discovery

```bash
git -C /workspace rev-parse --is-inside-work-tree && git -C /workspace status --short --branch
```

Result:

```text
true
## ide/category-leader-roadmap-047e...origin/ide/category-leader-roadmap-047e [ahead 1]
```

```bash
pytest -q tests/test_okf_retrieval.py
```

Result:

```text
--: line 1: pytest: command not found
```

```bash
python3 --version && python3 -m pytest --version
```

Result:

```text
Python 3.12.3
pytest 9.1.1
```

### TDD red run

```bash
python3 -m pytest -q tests/test_okf_retrieval.py
```

Result before implementation:

```text
ERROR tests/test_okf_retrieval.py
ModuleNotFoundError: No module named 'investigation_agent.okf_retrieval'
1 error in 0.12s
```

### Focused green run

```bash
python3 -m pytest -q tests/test_okf_retrieval.py
```

Result after implementation:

```text
.....                                                                    [100%]
5 passed in 0.23s
```

### Focused regression run

```bash
python3 -m pytest -q tests/test_okf_retrieval.py tests/test_knowledge_store.py tests/test_okf_registry.py
```

Result:

```text
.........................                                                [100%]
25 passed in 0.33s
```

## Behavior Verified

- Exact concept resolution happens before fallback search.
- Graph expansion from exact OKF seeds happens before memo RAG fill.
- Authority ordering keeps tenant OKF ahead of shared OKF and memo RAG.
- Indexed OKF rows with stale content hashes are excluded from authoritative results.
- Equal-authority same-source conflicts produce explicit conflict strings and `abstain=True`.
- Existing embedding failure behavior is preserved by propagating `keyword_fallback`.
- Frozen corpus recall@10 stays above the required 0.95 threshold, and unsupported rows abstain.

## Self-Review Notes

- Kept the retrieval module focused and standalone rather than wiring application lifecycle objects in this task.
- Reused `OkfRegistry.expand(..., max_depth=0)` for tenant-safe concept validation of indexed OKF RAG hits, avoiding new storage or services.
- Left memo-only retrieval non-authoritative, which matches the task requirement to abstain when curated support is missing.

## Concerns

1. The frozen corpus is intentionally focused on exact title/tag/concept-id and bounded link-expansion cases for this task; it is useful for Task 5 coverage but not yet a broad production evaluation set.
2. The new async facade is exported from `knowledge_store.py`, but application/tool wiring is intentionally deferred so Task 6 can connect it to request lifecycle state and citation handling cleanly.

## Review Fix Round

### Red run for review findings

```bash
python3 -m pytest -q tests/test_okf_retrieval.py
```

Result before review-fix implementation:

```text
.F.F...                                                                  [100%]
=================================== FAILURES ===================================
_________ test_authority_ranks_before_stage_when_rag_finds_tenant_okf __________
...
E       AssertionError: assert ['rules/high-...mount-review'] == ['playbooks/h.../high-amount']
...
_________ test_same_source_hash_conflict_abstains_before_deduplication _________
...
E       AssertionError: assert False is True
...
=========================== short test summary info ============================
FAILED tests/test_okf_retrieval.py::test_authority_ranks_before_stage_when_rag_finds_tenant_okf
FAILED tests/test_okf_retrieval.py::test_same_source_hash_conflict_abstains_before_deduplication
2 failed, 5 passed in 0.30s
```

### Green run after review fixes

```bash
python3 -m pytest -q tests/test_okf_retrieval.py
```

Result:

```text
.......                                                                  [100%]
7 passed in 0.29s
```

### Required regression runs after review fixes

```bash
python3 -m pytest -q tests/test_knowledge_store.py tests/test_okf_registry.py
```

Result:

```text
....................                                                     [100%]
20 passed in 0.21s
```

### Review-fix notes

- Updated ordering so authority is the primary sort key, with evidence presence, stage, and score breaking ties within the same authority tier.
- Conflict detection now runs on the pre-deduplicated candidate set, so same-source hash conflicts still abstain even when returned results collapse to a single canonical concept.
- Registry-backed exact and expanded candidates now document and assert the canonical-hash invariant explicitly; stale indexed OKF RAG hits remain excluded from returned authoritative results.
