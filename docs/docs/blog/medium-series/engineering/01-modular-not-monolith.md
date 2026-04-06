<!-- Medium: use this line as subtitle, not in body -->
<!-- Subtitle: Pick your services, keep the same decision contract -->

## The fraud monolith trap

Most teams don’t set out to build a monolith. They integrate one vendor, then another, then a spreadsheet, then a cron job that emails someone when a threshold trips. Five years later, “fraud” is a single deploy nobody wants to touch.

We took a different cut when we built **Tarka**. Fraud has natural seams: real-time scoring, batch-ish graph work, model inference, case management, and the glue that connects KYC or device vendors. Smashing that into one binary sounds simpler until you need to scale one path, patch another, or prove to an auditor *which* subsystem fired.

This post is for engineers who have to own that system after the launch party.

## What “modular” means here

Modular is not “microservices for sport.” It means **each major concern can ship, scale, and fail on its own boundary**, while clients still talk to a stable evaluate contract.

Rough mental model:

```
  Clients (SDKs)
        |
        v
  +-------------+
  | Decision API |  port 8000 — sync path, rules + orchestration
  +------+------+
         |
    +----+----+----------+-----------+
    v         v          v           v
  Redis    Postgres   ML :8005   Graph :8001
  tags     audit       ONNX       Neo4j
```

High-volume traffic can skip the hot path entirely for **event-ingest** (NATS on 4222) when you want async evaluation instead of holding a user on a POST. Same ideas, different latency budget.

The full architecture doc in the repo goes deeper (GraphQL gateway, analytics sink, integration ingress on 8003, etc.). The point for this post: **the Decision API is the hub**, not a kitchen sink that also renders PDFs.

## Why not one big “fraud service”?

**Blast radius.** If graph queries regress, you don’t want checkout latency tied to Neo4j lock contention. If ML inference OOMs, rules should still run.

**Ownership.** Backend teams can run decision + Redis + Postgres; data science can iterate on `ml-scoring` without redeploying case workflows.

**Honest dependencies.** Neo4j is powerful; it also carries license baggage some orgs care about. A separate **graph-service** means you can swap backends or run lite mode without pretending the graph never existed.

## The installer is part of the design

We ship `tarka.py` so “modular” isn’t only a diagram. You can start interactive, go `--all`, or use `--lite` when you want a working decision + cases + UI slice before you pay the cost of every profile.

```bash
python tarka.py install --lite
python tarka.py start
```

Docker Compose profiles mirror the same module boundaries. That sounds boring until you’ve watched someone debug a 40-container `docker-compose.yml` where half the services are optional.

## What we’d do differently if we started again

We’d still split decisioning from investigations. We might merge some observability noise earlier (shared tracing defaults across Python services). The lesson isn’t “microservices always win”; it’s **draw boundaries where your organization already argues**.

If your team argues about model releases weekly, ML shouldn’t live inside the same release train as a typo fix in a JSON rule pack.

## Where this goes next

Hardening the contract (OpenAPI, SDK typings), tightening CI so every service’s tests are a real gate, and making lite mode the honest default demo. If you’re evaluating the repo, skim `docs/docs/architecture.md` and open an issue if a boundary feels wrong for your shop. We’d rather fix a real integration pain than add another README adjective.

---

*Repo: [github.com/pamu512/tarka](https://github.com/pamu512/tarka)*
