# OKF-Enhanced RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Open Knowledge Format v0.1 bundles as reviewed, tenant-safe canonical knowledge while retaining Tarka's current hybrid RAG for broad discovery.

**Architecture:** The investigation agent loads one approved shared OKF bundle plus the authenticated tenant's overlay, resolves exact concepts and bounded links first, then searches the existing SQLite keyword/vector index. OKF and evidence identifiers flow into the existing `EvidenceItem`, `AgentRun`, citation and abstention paths; invalid candidate bundles never replace the last approved revision.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLite, PyYAML 6.0.3, existing OpenAI-compatible embeddings, Markdown/YAML OKF v0.1, pytest.

## Global Constraints

- OKF is canonical curated knowledge; the RAG index is derived and rebuildable.
- Shared bundles are read-only; tenant overlays are physically and logically isolated.
- Normal audits remain immutable evidence; only sanitized, approved landmark cases become OKF concepts.
- AI may generate staging proposals but cannot publish concepts or change fraud decisions.
- No new deployable service or graph database.
- Exact traversal precedes keyword/vector fallback.
- Invalid bundles fail atomically and the last approved revision remains active.
- All file paths are resolved beneath configured bundle roots; traversal and cross-tenant links are rejected.

---

## File Structure

Create:

- `services/investigation-agent/src/investigation_agent/okf_models.py` — OKF concept and validation result types.
- `services/investigation-agent/src/investigation_agent/okf_parser.py` — frontmatter parsing, path/link/hash validation.
- `services/investigation-agent/src/investigation_agent/okf_registry.py` — atomic shared/tenant bundle snapshots and bounded graph traversal.
- `services/investigation-agent/src/investigation_agent/okf_exporters.py` — deterministic exporters for rules, typologies, playbooks and landmark cases.
- `services/investigation-agent/src/investigation_agent/okf_retrieval.py` — authority-aware exact/graph/RAG merge.
- `services/investigation-agent/scripts/export_okf_bundle.py` — staging-bundle CLI.
- `services/investigation-agent/scripts/validate_okf_bundle.py` — CI validation CLI.
- `services/investigation-agent/tests/test_okf_parser.py`
- `services/investigation-agent/tests/test_okf_registry.py`
- `services/investigation-agent/tests/test_okf_exporters.py`
- `services/investigation-agent/tests/test_okf_retrieval.py`
- `services/investigation-agent/tests/fixtures/okf/shared/index.md`
- `services/investigation-agent/tests/fixtures/okf/shared/rules/high-amount.md`
- `services/investigation-agent/tests/fixtures/okf/tenants/t1/index.md`
- `services/investigation-agent/tests/fixtures/okf/tenants/t1/playbooks/high-amount-review.md`
- `services/investigation-agent/resources/okf_retrieval_corpus_v1.json`
- `knowledge/shared/index.md` — root shared bundle declaration.

Modify:

- `services/investigation-agent/pyproject.toml` — add PyYAML 6.0.3.
- `services/investigation-agent/src/investigation_agent/config.py` — OKF roots and traversal limits.
- `services/investigation-agent/src/investigation_agent/knowledge_db.py` — permanent OKF chunk metadata and shared/tenant scope search.
- `services/investigation-agent/src/investigation_agent/knowledge_store.py` — OKF-enhanced search facade.
- `services/investigation-agent/src/investigation_agent/tools.py` — return concept IDs, evidence IDs and retrieval paths.
- `services/investigation-agent/src/investigation_agent/main.py` — load registry, expose validation status, persist OKF-aware `AgentRun`.
- `services/investigation-agent/src/investigation_agent/citation_schema.py` — `okf_concept` citation artifact.
- `services/investigation-agent/.env.reference.example` — OKF configuration.
- `services/investigation-agent/Dockerfile` — copy approved shared bundle.
- `docs/docs/services/investigation-agent.md` — operator workflow and failure modes.
- `.github/workflows/ci.yml` — validate the committed shared bundle and frozen retrieval corpus.

---

### Task 1: Parse and Validate OKF v0.1 Concepts

**Files:**
- Create: `services/investigation-agent/src/investigation_agent/okf_models.py`
- Create: `services/investigation-agent/src/investigation_agent/okf_parser.py`
- Create: `services/investigation-agent/tests/test_okf_parser.py`
- Modify: `services/investigation-agent/pyproject.toml`

**Interfaces:**
- Produces: `parse_bundle(root: Path, *, scope: str, tenant_id: str | None) -> ParsedBundle`
- Produces: `validate_bundle(root: Path, *, scope: str, tenant_id: str | None) -> BundleValidation`
- Produces: immutable `OkfConcept`, `ParsedBundle`, `BundleIssue`, `BundleValidation`.

- [ ] **Step 1: Add the latest PyYAML dependency**

Add to `services/investigation-agent/pyproject.toml`:

```toml
"PyYAML==6.0.3",
```

Run:

```bash
python3 -m pip index versions PyYAML
```

Expected: `LATEST: 6.0.3`.

- [ ] **Step 2: Write parser tests**

Create tests that assert:

```python
def test_parse_concept_identity_and_links(tmp_path):
    root = tmp_path / "shared"
    (root / "rules").mkdir(parents=True)
    (root / "rules" / "r1.md").write_text(
        "---\n"
        "type: Fraud Rule\n"
        "title: High amount\n"
        "source_uri: rules/default.json#r1\n"
        "source_content_hash: " + "a" * 64 + "\n"
        "approval_status: approved\n"
        "approved_revision: abc123\n"
        "sensitivity: internal\n"
        "tenant_scope: shared\n"
        "---\n"
        "Use [the playbook](../playbooks/review.md).\n"
    )
    concept = parse_concept(root / "rules" / "r1.md", root, "shared", None)
    assert concept.concept_id == "rules/r1"
    assert concept.links == ("playbooks/review",)


def test_reject_path_traversal_link(tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    (root / "bad.md").write_text(
        "---\ntype: Reference\ntenant_scope: shared\n"
        "source_uri: docs/bad\nsource_content_hash: " + "b" * 64 + "\n"
        "approval_status: approved\napproved_revision: abc123\n"
        "sensitivity: internal\n---\n[escape](../../outside.md)\n"
    )
    result = validate_bundle(root, scope="shared", tenant_id=None)
    assert result.valid is False
    assert "link_outside_bundle" in {issue.code for issue in result.issues}


def test_reject_cross_tenant_scope(tmp_path):
    root = tmp_path / "t1"
    root.mkdir()
    (root / "bad.md").write_text(
        "---\ntype: Playbook\ntenant_scope: t2\n"
        "source_uri: playbooks/bad\nsource_content_hash: " + "c" * 64 + "\n"
        "approval_status: approved\napproved_revision: abc123\n"
        "sensitivity: internal\n---\nBad scope.\n"
    )
    result = validate_bundle(root, scope="tenant", tenant_id="t1")
    assert result.valid is False
    assert "tenant_scope_mismatch" in {issue.code for issue in result.issues}


def test_unknown_type_is_valid_generic_concept(tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    (root / "custom.md").write_text(
        "---\ntype: Custom Fraud Knowledge\ntenant_scope: shared\n"
        "source_uri: docs/custom\nsource_content_hash: " + "d" * 64 + "\n"
        "approval_status: approved\napproved_revision: abc123\n"
        "sensitivity: internal\n---\nCustom body.\n"
    )
    result = validate_bundle(root, scope="shared", tenant_id=None)
    assert result.valid is True
    assert result.bundle is not None
    assert result.bundle.concepts["custom"].concept_type == "Custom Fraud Knowledge"
```

- [ ] **Step 3: Run tests and confirm failure**

Run:

```bash
cd services/investigation-agent
pytest -q tests/test_okf_parser.py
```

Expected: collection fails because `investigation_agent.okf_parser` is absent.

- [ ] **Step 4: Implement immutable models**

`okf_models.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OkfParseError(ValueError):
    def __init__(self, code: str, path: Path, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message


@dataclass(frozen=True)
class OkfConcept:
    concept_id: str
    path: Path
    concept_type: str
    title: str
    description: str
    tags: tuple[str, ...]
    timestamp: str | None
    source_uri: str
    source_content_hash: str
    approval_status: str
    approved_revision: str
    sensitivity: str
    tenant_scope: str
    evidence_ids: tuple[str, ...]
    body: str
    links: tuple[str, ...]
    content_hash: str
    frontmatter: dict[str, Any]


@dataclass(frozen=True)
class BundleIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ParsedBundle:
    root: Path
    scope: str
    tenant_id: str | None
    revision: str
    concepts: dict[str, OkfConcept]


@dataclass(frozen=True)
class BundleValidation:
    valid: bool
    issues: tuple[BundleIssue, ...]
    bundle: ParsedBundle | None
```

- [ ] **Step 5: Implement strict parsing and validation**

`okf_parser.py` must:

```python
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_LINK = re.compile(r"\[[^\]]+\]\(([^)]+\.md(?:#[^)]+)?)\)")
_HASH = re.compile(r"^[0-9a-f]{64}$")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except ValueError:
        return False


def parse_concept(path: Path, root: Path, scope: str, tenant_id: str | None) -> OkfConcept:
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    if not match:
        raise OkfParseError("frontmatter_missing", path, "concept requires YAML frontmatter")
    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict) or not str(meta.get("type") or "").strip():
        raise OkfParseError("type_missing", path, "frontmatter.type is required")
    concept_id = path.resolve().relative_to(root.resolve()).with_suffix("").as_posix()
    links = tuple(_resolve_link_ids(match.group(2), path, root))
    required = (
        "source_uri", "source_content_hash", "approval_status",
        "approved_revision", "sensitivity", "tenant_scope",
    )
    missing = [key for key in required if not str(meta.get(key) or "").strip()]
    if missing:
        raise OkfParseError(
            "governance_field_missing", path, f"missing fields: {','.join(missing)}"
        )
    expected_scope = "shared" if scope == "shared" else str(tenant_id or "")
    if str(meta["tenant_scope"]).strip() != expected_scope:
        raise OkfParseError(
            "tenant_scope_mismatch", path,
            f"expected tenant_scope={expected_scope}",
        )
    source_hash = str(meta["source_content_hash"]).strip().lower()
    if not _HASH.fullmatch(source_hash):
        raise OkfParseError(
            "source_hash_invalid", path, "source_content_hash must be SHA-256 hex"
        )
    tags_raw = meta.get("tags") or []
    evidence_raw = meta.get("evidence_ids") or []
    return OkfConcept(
        concept_id=concept_id,
        path=path.resolve(),
        concept_type=str(meta["type"]).strip(),
        title=str(meta.get("title") or concept_id).strip(),
        description=str(meta.get("description") or "").strip(),
        tags=tuple(str(x).strip() for x in tags_raw if str(x).strip()),
        timestamp=str(meta["timestamp"]).strip() if meta.get("timestamp") else None,
        source_uri=str(meta["source_uri"]).strip(),
        source_content_hash=source_hash,
        approval_status=str(meta["approval_status"]).strip(),
        approved_revision=str(meta["approved_revision"]).strip(),
        sensitivity=str(meta["sensitivity"]).strip(),
        tenant_scope=str(meta["tenant_scope"]).strip(),
        evidence_ids=tuple(str(x).strip() for x in evidence_raw if str(x).strip()),
        body=match.group(2).strip(),
        links=links,
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        frontmatter=dict(meta),
    )
```

`validate_bundle` parses all non-reserved `.md` files, permits frontmatter only
on root `index.md`, validates every internal link target, rejects duplicate IDs,
and returns all issues without activating a partial bundle.

- [ ] **Step 6: Run parser tests**

Run:

```bash
cd services/investigation-agent
pytest -q tests/test_okf_parser.py
```

Expected: all parser tests pass.

- [ ] **Step 7: Commit**

```bash
git add services/investigation-agent/pyproject.toml \
  services/investigation-agent/src/investigation_agent/okf_models.py \
  services/investigation-agent/src/investigation_agent/okf_parser.py \
  services/investigation-agent/tests/test_okf_parser.py
git commit -m "feat(okf): parse and validate governed concept bundles"
```

---

### Task 2: Atomic Bundle Registry and Tenant-Safe Graph Traversal

**Files:**
- Create: `services/investigation-agent/src/investigation_agent/okf_registry.py`
- Create: `services/investigation-agent/tests/test_okf_registry.py`
- Create: `services/investigation-agent/tests/fixtures/okf/shared/index.md`
- Create: `services/investigation-agent/tests/fixtures/okf/shared/rules/high-amount.md`
- Create: `services/investigation-agent/tests/fixtures/okf/tenants/t1/index.md`
- Create: `services/investigation-agent/tests/fixtures/okf/tenants/t1/playbooks/high-amount-review.md`
- Modify: `services/investigation-agent/src/investigation_agent/config.py`

**Interfaces:**
- Consumes: `validate_bundle`.
- Produces: `OkfRegistry.reload() -> RegistryReloadResult`
- Produces: `OkfRegistry.resolve(tenant_id, query) -> list[ConceptHit]`
- Produces: `OkfRegistry.expand(tenant_id, concept_ids, *, max_depth, max_concepts) -> list[ConceptHit]`.

- [ ] **Step 1: Write registry isolation tests**

Cover exact shared lookup, tenant overlay lookup, no t1→t2 visibility, shared
concept precedence below tenant concepts, bounded cycles, and atomic reload:

```python
def test_invalid_reload_keeps_prior_snapshot(registry, shared_root):
    first = registry.reload()
    assert first.activated is True
    prior = registry.snapshot_revision("t1")
    (shared_root / "rules" / "high-amount.md").write_text("invalid")
    second = registry.reload()
    assert second.activated is False
    assert registry.snapshot_revision("t1") == prior
```

- [ ] **Step 2: Run registry tests and confirm failure**

```bash
cd services/investigation-agent
pytest -q tests/test_okf_registry.py
```

Expected: import failure for `okf_registry`.

- [ ] **Step 3: Add configuration**

Add settings with exact defaults:

```python
okf_enabled: bool = True
okf_shared_root: str = "knowledge/shared"
okf_tenant_root: str = "knowledge/tenants"
okf_max_link_depth: int = Field(default=2, ge=0, le=5)
okf_max_concepts: int = Field(default=24, ge=1, le=100)
```

- [ ] **Step 4: Implement snapshot registry**

Use a lock and immutable snapshot replacement:

```python
@dataclass(frozen=True)
class ConceptHit:
    concept: OkfConcept
    authority: str
    retrieval_path: tuple[str, ...]
    score: float


@dataclass(frozen=True)
class RegistryReloadResult:
    activated: bool
    revision: str
    issues: tuple[BundleIssue, ...]


class OkfRegistry:
    def reload(self) -> RegistryReloadResult:
        candidate = self._load_all()
        if candidate.issues:
            return RegistryReloadResult(False, self._snapshot.revision, candidate.issues)
        with self._lock:
            self._snapshot = candidate.snapshot
        return RegistryReloadResult(True, candidate.snapshot.revision, ())
```

Exact search checks concept ID, normalized title and tags. `expand` performs BFS,
tracks visited IDs, stops at both bounds, and never reads any tenant other than
the supplied tenant plus shared.

- [ ] **Step 5: Run registry tests**

```bash
cd services/investigation-agent
pytest -q tests/test_okf_registry.py
```

Expected: all tests pass, including cycle and isolation cases.

- [ ] **Step 6: Commit**

```bash
git add services/investigation-agent/src/investigation_agent/config.py \
  services/investigation-agent/src/investigation_agent/okf_registry.py \
  services/investigation-agent/tests/test_okf_registry.py \
  services/investigation-agent/tests/fixtures/okf
git commit -m "feat(okf): add atomic tenant-safe bundle registry"
```

---

### Task 3: Deterministic Exporters and Human-Gated Staging

**Files:**
- Create: `services/investigation-agent/src/investigation_agent/okf_exporters.py`
- Create: `services/investigation-agent/scripts/export_okf_bundle.py`
- Create: `services/investigation-agent/scripts/validate_okf_bundle.py`
- Create: `services/investigation-agent/tests/test_okf_exporters.py`
- Create: `knowledge/shared/index.md`

**Interfaces:**
- Produces: `export_rule_pack(pack, source_uri) -> dict[str, str]`
- Produces: `export_typologies(payload, source_uri) -> dict[str, str]`
- Produces: `export_playbooks() -> dict[str, str]`
- Produces: `export_landmark_case(case, *, tenant_id) -> str`
- Produces files only under a supplied staging root.

- [ ] **Step 1: Write deterministic exporter tests**

Assert two runs produce byte-identical files, one-byte source changes alter
`source_content_hash`, links are relative Markdown links, and landmark cases
reject raw PII keys:

```python
def test_landmark_case_rejects_unsanitized_pii():
    with pytest.raises(LandmarkCaseSanitizationError):
        export_landmark_case(
            {"case_id": "c1", "email": "person@example.com", "disposition": "fraud"},
            tenant_id="t1",
        )
```

- [ ] **Step 2: Run tests and confirm failure**

```bash
cd services/investigation-agent
pytest -q tests/test_okf_exporters.py
```

Expected: import failure for `okf_exporters`.

- [ ] **Step 3: Implement stable Markdown rendering**

Use sorted YAML keys, normalized line endings, sorted concepts and no generated
wall-clock timestamp:

```python
def render_concept(frontmatter: dict[str, Any], body: str) -> str:
    header = yaml.safe_dump(
        frontmatter,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    return f"---\n{header}\n---\n{body.strip()}\n"
```

Rule and typology exporters derive IDs from source IDs. Playbook exporters read
the existing `_PLAYBOOKS`. Landmark cases accept only an allowlist:
`case_id`, `title`, `typology_ids`, `rule_ids`, `disposition`,
`evidence_ids`, `summary`, `lessons`, `approved_revision`,
`source_content_hash`.

- [ ] **Step 4: Implement staging CLIs**

`export_okf_bundle.py` accepts:

```text
--rules-dir services/legacy_v1_decision_api/rules
--output var/okf-staging/shared
--include-playbooks
```

It refuses an output path containing the active shared/tenant roots.
`validate_okf_bundle.py ROOT --scope shared|tenant --tenant-id ID` exits 0 only
when `BundleValidation.valid` is true and prints issues as JSON otherwise.

- [ ] **Step 5: Run exporter tests and CLI validation**

```bash
cd services/investigation-agent
pytest -q tests/test_okf_exporters.py
python scripts/export_okf_bundle.py \
  --rules-dir ../legacy_v1_decision_api/rules \
  --output ../../var/okf-staging/shared \
  --include-playbooks
python scripts/validate_okf_bundle.py ../../var/okf-staging/shared --scope shared
```

Expected: tests pass and validator exits 0.

- [ ] **Step 6: Commit**

```bash
git add knowledge/shared/index.md \
  services/investigation-agent/src/investigation_agent/okf_exporters.py \
  services/investigation-agent/scripts/export_okf_bundle.py \
  services/investigation-agent/scripts/validate_okf_bundle.py \
  services/investigation-agent/tests/test_okf_exporters.py
git commit -m "feat(okf): export reviewed fraud knowledge to staging bundles"
```

---

### Task 4: Index Approved OKF Concepts in Existing Hybrid RAG

**Files:**
- Modify: `services/investigation-agent/src/investigation_agent/knowledge_db.py`
- Modify: `services/investigation-agent/src/investigation_agent/knowledge_store.py`
- Modify: `services/investigation-agent/tests/test_knowledge_store.py`

**Interfaces:**
- Consumes: `ParsedBundle`.
- Produces: `index_okf_bundle_async(http, bundle, *, embedding config) -> int`
- Existing `search_async` returns memo and OKF fields without breaking callers.

- [ ] **Step 1: Write migration and scope tests**

Write the following scope test, plus named tests
`test_existing_schema_migrates_without_data_loss` and
`test_okf_rows_survive_memo_ttl_pruning` using the same isolated DB fixture:

```python
def test_search_sees_shared_and_own_tenant_okf_but_not_other_tenant():
    index_okf_concepts_sync(shared_bundle, embeddings=None)
    index_okf_concepts_sync(t1_bundle, embeddings=None)
    index_okf_concepts_sync(t2_bundle, embeddings=None)
    hits = search("t1", "a1", "high amount", limit=20)
    ids = {h.get("concept_id") for h in hits}
    assert "rules/high-amount" in ids
    assert "playbooks/t1-review" in ids
    assert "playbooks/t2-secret" not in ids
```

- [ ] **Step 2: Run tests and confirm failure**

```bash
cd services/investigation-agent
pytest -q tests/test_knowledge_store.py
```

Expected: missing `index_okf_concepts_sync`.

- [ ] **Step 3: Extend the SQLite schema compatibly**

Add columns via `PRAGMA table_info` migration:

```sql
knowledge_kind TEXT NOT NULL DEFAULT 'memo'
concept_id TEXT
bundle_scope TEXT
content_hash TEXT
source_uri TEXT
authority INTEGER NOT NULL DEFAULT 10
```

Create a unique index on `(tenant_id, knowledge_kind, concept_id, chunk_index)`.
Represent shared concepts with tenant ID `__shared__` and analyst ID `__okf__`;
tenant concepts use the actual tenant and analyst ID `__okf__`.

- [ ] **Step 4: Add idempotent OKF indexing**

Delete/replace rows only when a concept content hash changes. OKF rows are not
subject to memo TTL or `_MAX_DOCS_PER_SCOPE`. Chunk text includes title,
description, tags and body. Store `authority=30` for tenant OKF, `20` for shared
OKF and `10` for memos.

- [ ] **Step 5: Expand scoped search**

The query must select:

```sql
WHERE (
  (tenant_id = ? AND analyst_id = ? AND knowledge_kind = 'memo' AND created_at >= ?)
  OR (tenant_id = ? AND analyst_id = '__okf__' AND knowledge_kind = 'okf')
  OR (tenant_id = '__shared__' AND analyst_id = '__okf__' AND knowledge_kind = 'okf')
)
```

Return `knowledge_kind`, `concept_id`, `bundle_scope`, `content_hash`,
`source_uri` and `authority` in every hit. Existing memo fields remain unchanged.

- [ ] **Step 6: Run knowledge tests**

```bash
cd services/investigation-agent
pytest -q tests/test_knowledge_store.py
```

Expected: existing and new tests pass.

- [ ] **Step 7: Commit**

```bash
git add services/investigation-agent/src/investigation_agent/knowledge_db.py \
  services/investigation-agent/src/investigation_agent/knowledge_store.py \
  services/investigation-agent/tests/test_knowledge_store.py
git commit -m "feat(rag): index approved OKF concepts with tenant isolation"
```

---

### Task 5: Exact Traversal, RAG Fallback and Authority Ranking

**Files:**
- Create: `services/investigation-agent/src/investigation_agent/okf_retrieval.py`
- Create: `services/investigation-agent/tests/test_okf_retrieval.py`
- Create: `services/investigation-agent/resources/okf_retrieval_corpus_v1.json`
- Modify: `services/investigation-agent/src/investigation_agent/knowledge_store.py`

**Interfaces:**
- Consumes: `OkfRegistry`, existing `search_async`.
- Produces: `retrieve_knowledge(...) -> KnowledgeRetrievalResult`.
- Result order: immutable evidence references, tenant OKF, shared OKF, memo RAG.

- [ ] **Step 1: Add frozen corpus and tests**

Corpus rows contain `tenant_id`, `query`, `expected_concept_ids`,
`unsupported`. Create named tests
`test_exact_and_graph_results_precede_rag`,
`test_results_deduplicate_by_concept_and_hash`,
`test_embedding_failure_uses_keyword_fallback`,
`test_equal_authority_conflict_requires_abstention`, and:

```python
def test_frozen_corpus_recall_at_10(registry, retrieval_corpus):
    resolved = 0
    expected = 0
    for row in retrieval_corpus:
        result = retrieve_knowledge(
            registry=registry,
            tenant_id=row["tenant_id"],
            analyst_id="corpus",
            query=row["query"],
            limit=10,
            rag_search=lambda **_: {"hits": [], "retrieval_mode": "keyword"},
        )
        actual = {item.concept_id for item in result.results if item.concept_id}
        wanted = set(row["expected_concept_ids"])
        resolved += len(actual & wanted)
        expected += len(wanted)
        if row["unsupported"]:
            assert result.abstain is True
    assert resolved / max(expected, 1) >= 0.95
```

- [ ] **Step 2: Run tests and confirm failure**

```bash
cd services/investigation-agent
pytest -q tests/test_okf_retrieval.py
```

Expected: import failure for `okf_retrieval`.

- [ ] **Step 3: Implement retrieval contracts**

```python
@dataclass(frozen=True)
class KnowledgeResult:
    text: str
    authority: str
    concept_id: str | None
    content_hash: str | None
    evidence_ids: tuple[str, ...]
    retrieval_path: tuple[str, ...]
    score: float
    stale: bool


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    results: tuple[KnowledgeResult, ...]
    retrieval_mode: str
    conflicts: tuple[str, ...]
    abstain: bool
    bundle_revision: str
```

- [ ] **Step 4: Implement staged retrieval**

`retrieve_knowledge`:

1. Calls `registry.resolve`.
2. Expands matched links within configured bounds.
3. Calls hybrid RAG only if exact/expanded results are below requested limit.
4. Drops stale concepts whose loaded content hash differs from indexed hash.
5. Deduplicates and sorts by authority then score.
6. Sets `abstain=True` when no authoritative result supports the query or when
   equal-authority concepts conflict on the same source URI/hash.

Embedding exceptions are caught only at the existing `search_async` boundary,
which returns `retrieval_mode="keyword_fallback"`.

- [ ] **Step 5: Verify retrieval quality**

```bash
cd services/investigation-agent
pytest -q tests/test_okf_retrieval.py
```

Expected: tests pass and corpus recall@10 is at least 0.95.

- [ ] **Step 6: Commit**

```bash
git add services/investigation-agent/src/investigation_agent/okf_retrieval.py \
  services/investigation-agent/src/investigation_agent/knowledge_store.py \
  services/investigation-agent/tests/test_okf_retrieval.py \
  services/investigation-agent/resources/okf_retrieval_corpus_v1.json
git commit -m "feat(rag): traverse OKF before hybrid retrieval fallback"
```

---

### Task 6: Wire Copilot Tools, Exact Citations and AgentRun

**Files:**
- Modify: `services/investigation-agent/src/investigation_agent/tools.py`
- Modify: `services/investigation-agent/src/investigation_agent/main.py`
- Modify: `services/investigation-agent/src/investigation_agent/citation_schema.py`
- Modify: `services/investigation-agent/tests/test_agent.py`
- Modify: `services/investigation-agent/tests/test_citation_schema.py`

**Interfaces:**
- Consumes: `retrieve_knowledge`.
- Produces tool result fields: `concept_id`, `content_hash`, `evidence_ids`,
  `retrieval_path`, `authority`, `bundle_revision`, `conflicts`, `abstain`.
- Produces citation artifact `okf_concept`.

- [ ] **Step 1: Write tool and citation tests**

Assert `search_knowledge` receives only authenticated tenant scope, never accepts
a bundle path, returns exact identifiers, and produces:

```json
{
  "artifact": "okf_concept",
  "id": "rules/high-amount"
}
```

Assert unsupported retrieval causes strict mode to return an abstention and an
`AgentRun` whose uncertainty includes `okf_abstain: true`.

- [ ] **Step 2: Run focused tests and confirm failure**

```bash
cd services/investigation-agent
pytest -q tests/test_agent.py -k "search_knowledge or okf"
pytest -q tests/test_citation_schema.py
```

Expected: missing OKF fields/artifact assertions fail.

- [ ] **Step 3: Extend citation schema**

Add `OKF_CONCEPT = "okf_concept"` to `CitationArtifact`. When a claim includes
`evidence_ids` or `concept_ids`, resolve every identifier exactly; unresolved
references force `supported=False`, `source="unknown"` and low confidence.

- [ ] **Step 4: Wire registry lifecycle**

At app lifespan:

```python
registry = OkfRegistry(
    shared_root=Path(settings.okf_shared_root),
    tenant_root=Path(settings.okf_tenant_root),
)
reload_result = registry.reload()
app.state.okf_registry = registry
app.state.okf_reload_result = reload_result
```

Readiness reports degraded (not process-fatal) if OKF fails but evidence tools
remain available. It reports unhealthy only when both OKF and the existing RAG
store are unavailable.

- [ ] **Step 5: Replace tool retrieval**

`tool_search_knowledge` calls `retrieve_knowledge` with `tenant_id` from the
tool executor, not model arguments. Preserve `query`, `limit` and
`retrieval_mode`; add exact OKF fields. Update the tool description to explain
that approved OKF is searched before uploaded memos.

- [ ] **Step 6: Persist retrieval lineage in AgentRun**

Collect concept/evidence IDs from successful knowledge tool calls:

```python
evidence_ids = sorted({
    evidence_id
    for call in tool_calls
    for hit in ((call.get("result") or {}).get("hits") or [])
    for evidence_id in (hit.get("evidence_ids") or [])
})
```

Set `uncertainty.okf_abstain`, `uncertainty.conflicts` and
`uncertainty.bundle_revision`. The copilot remains unable to write bundles.

- [ ] **Step 7: Run agent/citation tests**

```bash
cd services/investigation-agent
pytest -q tests/test_agent.py -k "search_knowledge or okf"
pytest -q tests/test_citation_schema.py
```

Expected: all focused tests pass.

- [ ] **Step 8: Commit**

```bash
git add services/investigation-agent/src/investigation_agent/tools.py \
  services/investigation-agent/src/investigation_agent/main.py \
  services/investigation-agent/src/investigation_agent/citation_schema.py \
  services/investigation-agent/tests/test_agent.py \
  services/investigation-agent/tests/test_citation_schema.py
git commit -m "feat(copilot): cite exact OKF concepts in AgentRun"
```

---

### Task 7: Packaging, CI, Documentation and End-to-End Gates

**Files:**
- Modify: `services/investigation-agent/.env.reference.example`
- Modify: `services/investigation-agent/Dockerfile`
- Modify: `docs/docs/services/investigation-agent.md`
- Modify: `.github/workflows/ci.yml`
- Create: `services/investigation-agent/tests/test_okf_end_to_end.py`

**Interfaces:**
- Uses all previous tasks.
- Produces reproducible image configuration and CI gates.

- [ ] **Step 1: Add end-to-end fallback and isolation tests**

Test:

1. Shared + t1 bundle activation.
2. Exact rule lookup expands to linked t1 playbook.
3. Unstructured memo fills remaining result slots through hybrid RAG.
4. Returned claims resolve exact concept/evidence IDs.
5. t2 concepts are absent.
6. Invalid reload keeps the prior revision.
7. Embedding failure yields keyword fallback.

- [ ] **Step 2: Run the end-to-end test and confirm failure**

```bash
cd services/investigation-agent
pytest -q tests/test_okf_end_to_end.py
```

Expected: failure until packaging/configuration is wired.

- [ ] **Step 3: Add deployment configuration**

Append:

```dotenv
OKF_ENABLED=true
OKF_SHARED_ROOT=/app/knowledge/shared
OKF_TENANT_ROOT=/var/lib/tarka/knowledge/tenants
OKF_MAX_LINK_DEPTH=2
OKF_MAX_CONCEPTS=24
```

Dockerfile:

```dockerfile
COPY knowledge/shared /app/knowledge/shared
ENV OKF_SHARED_ROOT=/app/knowledge/shared
ENV OKF_TENANT_ROOT=/var/lib/tarka/knowledge/tenants
```

The tenant root must be an operator-mounted writable volume; the application
still reads only approved revisions.

- [ ] **Step 4: Add CI gates**

In the investigation-agent CI job run:

```bash
python services/investigation-agent/scripts/validate_okf_bundle.py \
  knowledge/shared --scope shared
pytest -q \
  services/investigation-agent/tests/test_okf_parser.py \
  services/investigation-agent/tests/test_okf_registry.py \
  services/investigation-agent/tests/test_okf_exporters.py \
  services/investigation-agent/tests/test_okf_retrieval.py \
  services/investigation-agent/tests/test_okf_end_to_end.py
```

- [ ] **Step 5: Document operation and rollback**

Document:

- Staging export commands.
- Human Git approval and promotion.
- Shared/tenant mount locations.
- How exact traversal and RAG fallback appear in tool output.
- Failure states and readiness.
- Rollback by selecting the prior approved revision and rebuilding the index.
- Normal audits remain evidence; landmark cases require sanitization and review.

- [ ] **Step 6: Run complete verification**

```bash
cd services/investigation-agent
pytest -q
python scripts/validate_okf_bundle.py ../../knowledge/shared --scope shared
ruff check src tests scripts
ruff format --check src tests scripts
cd ../../frontend
npm test -- --run
```

Expected: all commands exit 0.

- [ ] **Step 7: Check the full diff**

```bash
git diff --check
git status --short
git diff --stat master...HEAD
```

Expected: no whitespace errors or untracked generated bundles/databases.

- [ ] **Step 8: Commit**

```bash
git add services/investigation-agent/.env.reference.example \
  services/investigation-agent/Dockerfile \
  services/investigation-agent/tests/test_okf_end_to_end.py \
  docs/docs/services/investigation-agent.md \
  .github/workflows/ci.yml
git commit -m "docs(okf): ship validation, deployment and rollback gates"
```

- [ ] **Step 9: Push and update the pull request**

```bash
git push -u origin ide/category-leader-roadmap-047e
```

Update the existing draft PR with the OKF implementation summary and exact
verification commands.
