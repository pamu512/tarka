# Contributing to Tarka

Thank you for helping improve Tarka. This guide is written for **beta testers** and **external contributors** who report bugs or open pull requests.

---

## Reporting bugs

1. **Search existing issues** on GitHub ([Issues](https://github.com/pamu512/tarka/issues)) for duplicates.
2. **Open a new issue** with a clear title and a description that includes:
   - **What you expected** vs **what happened**
   - **How to reproduce** (commands, API payload, or UI steps)
   - **Environment**: OS, Docker version (if using compose), branch or release tag, relevant service ports
   - **Logs or screenshots** (redact secrets, tokens, and PII)
3. For **security-sensitive** findings (authentication bypass, remote code execution, credential leakage), do **not** file a public issue until coordinated disclosure; contact the maintainers through a **private** channel if one is published in the repository security policy.

Maintainers may label issues, request more detail, or close duplicates.

---

## Submitting pull requests

### 1. One logical change per PR

Keep each pull request focused on a single concern (one bug, one feature, or one docs/tooling update). Split unrelated edits into separate PRs.

### 2. Branch from the correct base

- **Beta / release testing:** branch from the **release branch** or tag your beta build tracks (for example `1.3.0-beta`), unless maintainers direct you to `main`.
- **General contributions:** branch from **`main`** unless an issue says otherwise.

### 3. Local checks before you push

Run the checks your change touches (examples—adjust paths to match the service you edited):

- **Tests:** `pytest` for the affected package or `tarka_v2_core` subtree.
- **Lint:** **`ruff check`** (and format if the project uses `ruff format`) on changed Python trees.

CI failures on Ruff or tests block merge.

### 4. Open the PR on GitHub

1. Push your branch to **your fork** (or to the upstream repo if you have write access).
2. On GitHub, choose **Compare & pull request** (or use [`gh pr create`](https://cli.github.com/manual/gh_pr_create)).
3. **Pull request description:** GitHub **automatically pre-fills** the body from [`.github/pull_request_template.md`](.github/pull_request_template.md). Do not delete the **Review checklist**; complete every item honestly (use the **AuditLog schema N/A** line only when no audit persistence changed).

If you use the GitHub CLI and the editor does not open the default template, pass it explicitly:

```bash
gh pr create --template .github/pull_request_template.md
```

### 5. Review checklist (required)

Every PR must reflect the template checklist:

| Item | Meaning |
|------|--------|
| **Has tests?** | New behavior is covered by automated tests; existing suites still pass. |
| **Passes Ruff?** | `ruff check` is clean for the touched code (CI enforces this). |
| **Updates AuditLog schema?** | If you change audit persistence (`AuditLog`, migrations, or related ORM), migrations and docs are included; otherwise mark **N/A** per the template. |

### 6. Deterministic AST policy (non-negotiable)

Any PR that **breaks** or **introduces nondeterminism** into **JSON rule AST** evaluation—how `when_ast` / leaf operators combine, ordering guarantees, or parity with the shipped evaluator contract—**will be rejected** unless maintainers have approved a **written spec change** and you ship **full regression tests** proving behavior. Do not “simplify” or reorder evaluation for convenience without that review.

---

## Gate check (for maintainers): verify the PR template on GitHub

GitHub loads the default template from [`.github/pull_request_template.md`](.github/pull_request_template.md) on the repository’s **default branch** (this repo: `master`). Until that file exists on `master`, the web UI will not inject it.

**Web UI (authoritative “automatic inject” check):**

1. Merge or cherry-pick the template file to `master` (or open a PR that adds it and merge).
2. On **github.com**: **Pull requests → New pull request** → choose a **feature branch** that is **not** already tied to an open PR (GitHub only shows the template when composing a **new** PR).
3. Confirm the description field opens with this repo’s template, including the three unchecked checklist lines: `Has tests?`, `Passes Ruff?`, `Updates AuditLog schema?`

**CLI (same markdown as the template body):**

Non-interactive `gh pr create` requires `--body` or `--body-file`; it does not merge the default template unless you pass `--template` **and** satisfy `gh`’s title/body flags. To dry-run the exact checklist text:

```bash
gh pr create --dry-run --draft \
  --title "chore: verify PR template (dummy)" \
  --body-file .github/pull_request_template.md
```

Use a branch that does not already have an open PR, or add `--head youruser:your-branch`.

**Local sanity check (no GitHub API):**

```bash
grep -E '^- \\[ \\] (Has tests\\?|Passes Ruff\\?|Updates AuditLog schema\\?)$' .github/pull_request_template.md
```

All three lines must match.

---

## Questions

Open a [Discussion](https://github.com/pamu512/tarka/discussions) or comment on an existing issue if you are unsure whether a change fits the AST or audit rules.
