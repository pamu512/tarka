<!-- Subtitle: Tests, containers, and the boring stuff that keeps OSS honest -->

## Open source is easy to publish, hard to maintain

Anyone can push a README. Keeping **main** green when strangers run your compose file on Windows WSL, ARM Macs, and a CI runner you don’t control is another job. We built Tarka as something you could actually run, not as a slide deck.

This post is the engineering view of **how we ship** and **what’s next**.

## CI as product

GitHub Actions isn’t glamorous. It is the first impression when a contributor opens a PR.

Our CI matrix is intentionally wide: **Ruff** on Python, **pytest** per service where it exists, **npm run build** on the frontend and TypeScript SDK, **Docker builds** gated so a broken image doesn’t become the default onboarding path. Decision API carries a **coverage floor** (45% with room to climb) so “it works on my laptop” doesn’t regress silently.

Security side: **Trivy** on the filesystem and the decision-api image, **Dependabot** grouped so noise doesn’t train people to ignore alerts. None of that stops zero-days; it raises the baseline.

If you fork the repo, treat failing CI as a feature: it’s cheaper than production paging.

## Install paths we care about

Three entry points show up in issues more than the rest:

1. **`python tarka.py install --lite`** — core + cases + frontend for a believable demo.
2. **`deploy/docker-compose.lite.yml`** — matches the “five minute” sandbox path with integration-ingress (8003) where we want OSINT without standing up Neo4j.
3. **`.devcontainer`** — Codespaces / VS Code remote; Docker-outside-Docker so contributors aren’t hand-editing `/etc/hosts` for fun.

The CLI and compose files can drift; when they do, we fix it as a release blocker, not a FAQ entry.

## Roadmap without fantasy dates

Concrete threads on trunk and near trunk:

- **v1.1.0** — hardening: tests, CI, security docs, onboarding polish.
- **SDK coverage** — mobile and web collectors staying aligned with the same device/signal JSON contracts the Decision API expects.
- **Graph** — Neo4j today; docs already acknowledge **AGPL** friction and alternate backends for teams that need Apache-friendly graphs.
- **OSS adoption backlog** — issues grouped in docs so drive-by contributors know what unblocks what.

We publish release notes and a schedule file in-repo; Medium isn’t the source of truth for dates. Check `RELEASE_SCHEDULE.md` and `docs/docs/releases/` when you need specifics.

## How we want contributions to land

Small PRs beat heroic rewrites. If you touch the evaluate contract, touch **OpenAPI + SDKs + a test** in the same change. If you add a service, add **health checks** and a **compose profile** so `tarka.py list` stays honest.

## Diagram: from commit to runnable stack

```
  git clone
      |
      v
  python tarka.py install [--lite | --all | --modules ...]
      |
      v
  .tarka/install.json  +  generated compose overlay
      |
      v
  python tarka.py start
      |
      v
  health: decision-api :8000, case-api :8002, ...
```

## Closing

The “way forward” for Tarka is unglamorous: fewer sharp edges on first run, more parity between docs and code, and a community that treats fraud as infrastructure worth sharing. If you want to help, pick an issue labeled **good first issue** or open one that names your deployment target (cloud, on-prem, air-gapped). We learn more from that than from another Twitter thread about AI.

---

*Repo: [github.com/pamu512/tarka](https://github.com/pamu512/tarka) · Security: `SECURITY.md` · Scanning guide: `docs/docs/guides/security-scanning.md`*
