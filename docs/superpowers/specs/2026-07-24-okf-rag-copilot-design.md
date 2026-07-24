# OKF-Enhanced RAG for the Tarka Copilot

## Objective

Use Open Knowledge Format (OKF) v0.1 to add curated, linked and reviewable
knowledge to Tarka's existing hybrid RAG system. OKF does not replace RAG:
approved OKF concepts provide deterministic navigation and authority, while
keyword/vector retrieval continues to discover relevant unstructured material.

The copilot remains read-only and evidence-grounded. Deterministic rules and
immutable decision evidence remain authoritative.

## Scope

The first implementation covers both:

- Fraud rules, typologies and decision evidence references.
- Analyst playbooks, SOPs, investigation memos and approved landmark cases.

Normal decision audits remain in the immutable evidence store. They do not
become OKF files. Sanitized landmark cases may be promoted into OKF only after
human approval.

## Architecture

```text
Approved sources
  rules + typologies + playbooks + landmark cases
                |
        deterministic exporters
                v
 Shared OKF bundle + tenant overlay bundle
                |
        validate links/frontmatter
                v
 Existing hybrid RAG index
                |
Query -> exact concept match -> linked-concept expansion
      -> semantic/keyword fallback -> immutable evidence lookup
                v
 Context assembler -> exact evidence citations -> copilot
```

OKF bundles are canonical, Git-reviewed knowledge. The RAG index is derived and
rebuildable. Agent-generated updates are proposals only: they enter a staging
bundle and cannot become canonical knowledge without human approval.

No new service is introduced. The implementation extends the investigation
agent's existing knowledge store and retrieval path.

## Bundle Layout

```text
knowledge/
  shared/
    index.md
    rules/
    typologies/
    playbooks/
  tenants/<tenant-id>/
    index.md
    rules/
    playbooks/
    landmark-cases/
```

Shared concepts are read-only to tenants. Tenant overlays are physically and
logically isolated and may link to shared concepts. Shared concepts must never
link to tenant concepts. Cross-tenant links are invalid.

Each concept is a Markdown file with YAML frontmatter. Its file path without
the `.md` suffix is its stable OKF concept ID.

Required metadata:

- `type`: OKF-required concept type.
- `title`, `description`, `tags`, `timestamp`.
- `source_uri`: canonical source location.
- `source_content_hash`: immutable hash of the exported source.
- `approval_status` and `approved_revision`.
- `sensitivity` and `tenant_scope`.
- `evidence_ids`: exact runtime evidence references, when applicable.

Initial concept types:

- `Fraud Rule`
- `Fraud Typology`
- `Investigation Playbook`
- `Landmark Case`
- `Evidence Reference`

Markdown links express relationships between concepts. Unknown concept types
remain readable as generic concepts, as required by OKF v0.1.

## Production and Approval

Deterministic exporters generate candidate concepts from approved source
material:

- Active rule packs and their content hashes.
- Typology definitions.
- Approved playbooks and SOPs.
- Sanitized landmark-case promotion records.

Generated concepts are written to a staging bundle. Promotion requires:

1. OKF v0.1 frontmatter and path validation.
2. Internal-link and backlink validation.
3. Tenant-boundary validation.
4. Source-content-hash verification.
5. Landmark-case sanitization validation.
6. Human-reviewed Git merge.

Validation failure rejects the whole candidate promotion. The last approved
bundle remains active.

## Retrieval Flow

For each copilot query:

1. Classify intent as rules, typologies, playbooks, cases or mixed.
2. Resolve exact concept IDs, titles and tags in the shared bundle and the
   requesting tenant's overlay.
3. Expand explicit OKF links with configured depth and concept-count limits.
4. Run existing hybrid keyword/vector RAG when exact traversal is insufficient.
5. Fetch current audits and case evidence through tenant-aware, read-only tools.
6. Rank candidates by authority, tenant scope, freshness and relevance.
7. Assemble context containing exact concept IDs, content hashes and evidence
   IDs.
8. Validate factual claims against those identifiers.
9. Abstain when evidence is missing, stale, conflicting or out of scope.

Authority order:

```text
Immutable decision evidence
> tenant-approved OKF
> shared-approved OKF
> unstructured RAG results
> model prior knowledge
```

RAG results may suggest knowledge candidates but cannot override approved OKF
or deterministic decision evidence. Conflicts are returned explicitly to the
analyst.

## Component Boundaries

### OKF parser and validator

Reads bundles without a service dependency. It validates frontmatter, concept
IDs, links, source hashes and tenant boundaries. Parsing is read-only.

### Deterministic exporters

Convert existing rule, typology, playbook and landmark-case records into
stable OKF concepts. Identical source content produces identical concept
content.

### Bundle registry

Loads one approved shared bundle and one approved tenant overlay per request.
It records bundle revision and content hash for citation and replay.

### Graph-aware retriever

Performs exact lookup and bounded Markdown-link expansion before calling the
existing hybrid RAG retriever. Its result contract includes concept ID, bundle
revision, source hash, retrieval path and score.

### Context and citation adapter

Converts OKF results into the existing `EvidenceItem` and `AgentRun` contracts.
Claims cite exact concept and evidence IDs; unresolved citations are marked
unsupported.

## Failure Behaviour

- Invalid bundle: reject promotion and keep the last approved revision.
- Broken or cross-tenant link: reject promotion and emit an audit event.
- RAG unavailable: continue with exact OKF traversal and evidence tools.
- OKF unavailable: use evidence tools and mark curated knowledge unavailable.
- Embedding failure: fall back to keyword retrieval.
- Stale source hash: exclude the concept from authoritative context.
- Missing or conflicting support: abstain and show the conflict.

Rollback consists of selecting the prior approved bundle revision and rebuilding
the derived RAG index.

## Security

- Bundle selection is server-side from the authenticated tenant; clients cannot
  supply arbitrary bundle paths.
- Path normalization prevents traversal outside approved bundle roots.
- Tenant overlays cannot reference another tenant's concepts.
- Retrieved content is still subject to prompt-injection handling and
  sensitivity policy.
- AI tools are read-only. Concept publication and material case/decision
  changes require existing RBAC, idempotency and human approval.
- Landmark-case exporters must remove or pseudonymize restricted PII before
  staging.

## Verification Gates

- 100% tenant-isolation tests across bundles, indexes and evidence tools.
- 100% promoted concepts pass OKF v0.1 validation and link checks.
- At least 99.5% returned concept/evidence citations resolve exactly.
- At least 98% unsupported questions abstain.
- At least 95% retrieval recall@10 on a frozen fraud-question corpus.
- No AI-authored concept bypasses human approval.
- Existing RAG remains usable during migration and rollback.

Unit coverage includes malformed frontmatter, path traversal, broken links,
cross-tenant links, stale hashes, deterministic export, bounded graph traversal,
authority ranking, exact citations and fallback behaviour. Integration coverage
compares the current RAG path with OKF-enhanced retrieval on a frozen corpus.

## Delivery Boundaries

The first release uses the existing SQLite-backed keyword/vector index. It does
not add a graph database or OKF service. Projecting OKF links into Tarka's graph
service is deferred until measured retrieval failures justify the synchronization
cost.

## References

- [Open Knowledge Format v0.1 specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
- [Google Cloud OKF introduction](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing)
