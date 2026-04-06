<!-- Subtitle: Three lenses on the same customer, without the buzzwords -->

## Fraud programs use three muscles

Most mature programs don’t rely on a single trick. They use:

1. **Policies you can read** (if X and Y, then Z).
2. **Patterns that learn from data** (this *looks* like things we’ve labeled bad before).
3. **Relationships** (this account touches the same phone number, device cluster, or mule chain as known abuse).

Engineers map those to **rules**, **machine learning**, and **graph** work. Risk owners feel them as **playbooks**, **models**, and **link analysis**. Same ideas, different vocabulary.

Tarka keeps all three behind one **decision** surface so product teams aren’t juggling three vendors just to answer “should we approve this login?”

## Rules: the control you can sign

Rules are the boring hero. They’re auditable, versionable, and easy to simulate in shadow mode before you flip production traffic.

```
  IF  country_change_in_10min
  AND new_device
  THEN route_to_review
```

That’s oversimplified, but the point stands: **someone can explain this in a meeting** without a PhD slide.

In Tarka, JSON rule packs load into the Decision API. You can run **A/B or shadow tests** (see repo docs on shadow testing) so policy changes don’t have to be binary “ship or don’t.”

## ML: speed and drift, not magic

Models are good at fuzzy similarity: bot behavior, transaction shape, device anomalies. They’re bad at being **the only** line of defense, because they age. Fraud actors adapt; your training data doesn’t update itself.

We run **ONNX** inference in a dedicated scoring path so models can be swapped and versioned like any other dependency. Adaptive pieces in the stack are aimed at catching **behavior drift** before revenue quietly leaks.

Risk translation: **don’t buy “AI” as a black box**. Buy **a model you can version, monitor, and roll back**.

## Graph: rings, not rows

Spreadsheets think in rows. Fraud rings think in **shared attributes**: addresses, IBANs, device fingerprints, invite trees.

```
   [User A]----phone----[User B]
       |                    |
    device              device
       \                  /
        \                /
         [  same cluster  ]
```

Graph analysis answers questions spreadsheets struggle with: *how connected is this applicant to known fraud?* *is this a lone bad actor or part of a batch?*

Tarka’s graph service sits behind Neo4j today. If your legal team chafes at certain database licenses, the project documents **alternate graph backends**; the architectural point is the **capability**, not a single vendor lock.

## How they combine at decision time

You don’t pick one lens. The Decision API **orchestrates**: rules fire, ML may contribute a score or features, graph may add link risk, then the system merges everything into **one outcome** plus the structured **evidence** we described in the companion post.

```
        Customer action
              |
              v
         Decision API
         /    |     \
        v     v      v
     Rules   ML    Graph
        \     |     /
         \    |    /
          v   v   v
       Single outcome + evidence + tags
```

## What you should expect from your engineering partner

Ask for a **plain-English map** of which subsystem can override which, and what happens when one is down. “Fail open” vs “fail closed” is a business choice, not a technical default handed down from the sky.

## Closing

If you only remember one thing: **rules, ML, and graph answer different questions**. A stack that treats them as optional modules lets you **start strict** (rules + cases) and **add sophistication** without replacing your core decision pipe every two years.

---

*Technical deep dive for your team: `docs/docs/architecture.md` in [github.com/pamu512/tarka](https://github.com/pamu512/tarka)*
