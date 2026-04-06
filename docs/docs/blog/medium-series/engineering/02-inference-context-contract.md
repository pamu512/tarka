<!-- Subtitle: One endpoint, three kinds of answers -->

## Scores lie by omission

A float from 0 to 1 tells you how anxious the model is. It does not tell you whether the payload looked replayed, whether the IP reputation was thin, or whether velocity alone would have tripped a rule. Support asks “why?” and you’re stuck grepping logs.

When we designed the **evaluate** response for Tarka, we stopped treating the score as the whole message. The score stays; it’s joined by **`inference_context`** and **tags** so downstream systems (and humans) can answer follow-up questions without a séance.

## The shape we standardized on

Conceptually, one POST returns three buckets:

```
POST /v1/decisions/evaluate
            |
            v
    +-------+-------+
    |    Response    |
    +---+---+---+---+
        |   |   |
        v   v   v
   decision  inference_context  tags
   (allow/   (structured         (rule_hits,
    review     signals: replay,     attributions,
    deny)      network, geo,       short codes)
               velocity, ...)
```

**Decision** is the product outcome: what should the app do next?

**inference_context** is the engineering truth serum: normalized fields like integrity confidence, tamper risk, network trust, replay risk, geo-consistency, velocity windows, `top_signals`, driver reasons. Your frontend can surface them; your SIEM can index them.

**Tags** stay string-friendly for Redis, dashboards, and “why did this user get `device:vpn`?” questions.

Python and TypeScript SDKs expose typed `InferenceContext` so you don’t rediscover field names from JSON every sprint.

## Why not stuff everything into tags?

Tags are great for cardinality-controlled rollups. They’re a lousy place for “velocity_events_24h = 37” if you want charts and thresholds without parsing strings. Splitting structured metrics into `inference_context` keeps **analytics honest** and keeps **tags readable**.

## Replay and Redis

Replay-style detection shows up in scoring *and* in the audit context. Short-lived Redis signatures are the kind of detail that sounds minor until someone clones a payment form and replays bodies. Wiring that into the same response object means your case UI and your API consumer see the same story.

## Contract discipline

OpenAPI and SDK generation are only useful if the server actually matches them. We treat drift between docs and handlers as a bug, not documentation debt. That’s dry to write; it’s less dry when your mobile team ships against a stale field name the night before a launch.

## Flow: where context gets built

```
  Request body (device, signals, transaction, ...)
                    |
                    v
            Decision API pipeline
                    |
      +-------------+-------------+
      |             |             |
      v             v             v
   Rule packs    ML scoring    Graph lookups
   (JSON)        (ONNX etc.)   (optional)
      |             |             |
      +-------------+-------------+
                    |
                    v
         Merge -> inference_context + tags + decision
```

Not every install runs graph or ML on every call. The contract still has a stable place for “what we knew when we decided.”

## If you’re implementing something similar

Pick a **schema version** inside `inference_context` early. Add fields additively. Version bumps beat silent renames. Your future self is the one debugging a/b tests across two mobile app versions.

---

*Repo: [github.com/pamu512/tarka](https://github.com/pamu512/tarka) · Evaluate clients: `packages/fraud-sdk-python`, `packages/fraud-sdk-typescript`*
