# Saarthi Pro — release notes template

> **Internal.** Copy into Saarthi-pro `CHANGELOG.md` or `RELEASE.md` per version.

---

## Saarthi Pro [X.Y.Z] — [YYYY-MM-DD]

### Summary

[One paragraph: theme of release—security, contract bump, packaging only, etc.]

### Integration contract

| Field | Value |
|-------|--------|
| **`contract_version`** (from `GET /v1/integration`) | e.g. `1.1.0` |
| **OSS reference** | fraud-stack commit `[full SHA]` (tag `[optional tag]`) |
| **CHANGELOG_INTEGRATION** | Link or section: [CHANGELOG_INTEGRATION.md](CHANGELOG_INTEGRATION.md#110-2026-04) |

### Breaking changes

- [None | List with migration steps]

### Security

- [CVE fixes, dependency bumps, rotated base images]

### Configuration

- New or changed env vars: [table]
- Recommended default changes: [bullets]

### Upgrade

- From Pro [X.Y.Z-1]: [steps]
- From OSS reference: [link to upgrade guide](saarthi-pro-upgrade-from-oss.md)

### Artifacts

- Container: `[your-registry]/[saarthi-pro-image]:X.Y.Z@sha256:…` (image name and registry live in **private** [Saarthi-pro](https://github.com/pamu512/Saarthi-pro))
- Helm chart: `[version]`

### Known issues

- [Bullets]

---

## Saarthi Pro [X.Y.Z-1] — …

*(older entries below)*
