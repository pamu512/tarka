<!--
MEDIUM PUBLISHING
Title:    Goalposts That Move: A Self-Reflection on Working in Anti-Fraud
Subtitle: What I have learned about hype, legibility, and the gap between the roadmap and the reality.
-->

**Note:** *I am building [Tarka](https://github.com/pamu512/tarka). The links below are disclosure, not a pitch—if the ideas stand, they stand without the repo.*

---

# Goalposts That Move: A Self-Reflection on Working in Anti-Fraud

*What I have learned about hype, legibility, and the gap between the roadmap and the reality.*

---

I have spent enough time in anti-fraud to stop believing in clean endings.

The work rewards people who care about detail—signals, policies, edge cases, the slow grind of making “fraud” and “not fraud” mean something stable for a week at a time. It also punishes anyone who expects that grind to **look** like a normal engineering roadmap. The goalposts do not stay put. The environment is adversarial; the product changes; the data drifts; what was “good enough” last quarter is a liability after one bad week. That is not poor planning. It is the job.

This piece is a reflection on **what that feels like now**: the tools we are sold, the friction we hit inside our own organizations, and what I think actually helps.

---

## What “basics” means in practice

People talk about getting the basics right—definitions, data quality, labels, sensible rules, solid features. I still believe in that. I also know that **basics are not a one-time achievement**. They are something you keep re-earning as the business and the attackers move.

The hard part is not the first time you line up a pipeline or ship a model. It is the **nth** iteration: monitoring, revisiting assumptions, arguing about tradeoffs with legal and product, swallowing the fact that “done” is a story we tell finance, not a property of the control itself.

---

## Friction with people who have never lived here

I once tried to explain to a **senior engineering leader** why fraud work does not behave like a standard product backlog—the target moves because the **problem** moves. The conversation did not land. I have stopped treating that as a personal failure.

People who have not worked in fraud often **do not map how messy it is**—or, honestly, **do not want to**, because acknowledging the mess complicates staffing, timelines, and the comforting idea that software ships and then stays finished. The gap is not always malice. It is **distance**. Sometimes it is also **misaligned incentives**: growth targets, launch dates, and headcount math can punish the person who says “not yet” even when everyone agrees fraud is real. The outcome is still **friction**: pressure to pretend the work is finite, less air for monitoring and governance, more second-guessing of the people closest to the pain.

That friction shapes how I think about tooling. I care less about another abstract “score” and more about whether anyone can **explain** a decision when a customer, a regulator, or a teammate asks *why* months later.

---

## What good leadership does instead of faking a sprint

The best leaders I have seen do **not** pretend every fraud initiative has a fixed scope. They **budget for response**: on-call and review capacity, explicit **outcome** milestones (loss rates, dispute SLAs, false-positive pain), **game days** and simulations before big launches, and a shared language that **change** in controls is normal—not a sign the last sprint “failed.” They separate **predictability of delivery** for *infrastructure* from **honesty** about *adaptive* work. That does not make the job easy; it makes the org **honest**. I mention this because the alternative—forcing fraud into a standard template—is not the only management style out there, and blaming “leadership” wholesale would be unfair.

---

## AI, hype, and what I actually trust

I am skeptical of anyone who says AI will “solve” fraud. I am equally skeptical of the opposite posture—**dismissing models** while quietly renting someone else’s black box and still not being able to reconstruct what happened at decision time.

The failure mode I see most often is not “too much math.” It is **mystery**: a number on a screen, a vendor payload, tribal knowledge in Slack. Many vendors now ship richer APIs, reason codes, or sandboxes; the failure mode I still care about is **operational**—when, in practice, **your** systems cannot replay what was known at decision time. You can get a long way with **immutable decision records in your warehouse** and a **contract** that defines what “explain” means—Tarka is not the only way to earn that.

Anti-fraud teams need **inspectable** automation: reasons, replay, evidence that travels with the outcome. In consumer-facing products, “why” is not only an engineering nicety—it is often **adjacent to adverse-action and fairness narratives**: you need a story that holds up when someone asks for it in plain language, not only when an engineer opens a trace.

**Disclosure, again:** I put energy into **[Tarka](https://github.com/pamu512/tarka)** partly because of that gap—an open, modular stack so evaluation returns **homework**, not just a label: structured context, tags, a shared story between APIs and case work. The name nods at **tarka** in the sense of reasoning with reasons. If that sounds like a product paragraph, treat it as **why I am building**, not a claim that you must buy the premise to agree with the rest of this essay.

---

## Orchestration and copilots are the heavy lifting

The durable story about AI in our field is not “replace the analyst.” It is **orchestration** and **copilots**—routing, prioritization, assistive workflows. I agree, and I do not think that is a small job. Orchestration without a single source of truth for decisions becomes meetings and spreadsheets. Copilots without grounded signals become fast ways to codify bad habits.

If orchestration is the real product, the bet is whether your system can **unify** real-time decisioning, investigations, integrations, and audit in one **legible** path. Modular design—a **Decision API** at the center, graph, ML, cases, integrations attaching when you are ready—matches how I think about **owning** the story end to end, whether you use Tarka or not. Modularity is not free: **someone** still owns the **contract** between services, versioning, and failure modes—that integration tax is the price of flexibility.

---

## Notebooks, languages, and the loop that never closes

Python and R still matter. So does a serious labeling discipline. I would not be employable without them.

They are also **not sufficient** on their own. Labels arrive late; they reflect who got investigated and who did not; they carry policy and politics. Production success is bounded by **feedback loops**—chargebacks, disputes, case outcomes—and by whether your organization funds the **boring** work of closing those loops. Software should make that repeatable, not heroic.

Most fraud organizations are **not** notebook farms: they are **queues**, **SLAs**, and **analyst judgment** under time pressure. When I talk about legibility, I mean **for them** as much as for engineers—if only engineering can interpret the system, you have rebuilt mystery with extra steps.

---

## Cost and honesty

A full stack you run yourself is **not** free: people, security, uptime, and opportunity cost. Smaller shops sometimes need a **point** solution first; that can be rational. **Full replay** for every signal on every low-stakes flow can be **overkill**; proportionality matters—what you store and replay should match **risk and regulatory exposure**, not a purity contest.

What I am arguing for here is not “everyone should run everything”—it is **legibility and accountability** at whatever scale you can afford. The worst place to be is **paying** for opacity and still **owning** the customer and regulator fallout.

---

## Where I land

Working in anti-fraud right now feels like **holding rigor and uncertainty at the same time**: respect the fundamentals, distrust easy narratives from vendors and from leaders who have never had to explain a block to a customer, and build systems that make **proof** normal—not because the work ever “finishes,” but because someone will always ask *why*.

I have seen good people strained by a world that wants **predictability of scope** where only **predictability of process** is realistic. I would rather put energy into software that makes decisions **auditable** and **extensible**—and that is what I am trying to do with Tarka, without pretending one repo fixes an industry.

The goalposts move. The work is still worth doing if we are honest about what it is—and if we admit that **some** leaders already know how to plan for that without calling it a sprint.

---

**Tarka** — open-source, modular fraud detection: rules, ML, graph, cases, and integrations behind a Decision API you can run and extend.  
[github.com/pamu512/tarka](https://github.com/pamu512/tarka)
