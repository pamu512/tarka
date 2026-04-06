<!--
MEDIUM PUBLISHING
Title:    Your Fraud Vendor Gave You a Number. Your Customer Asked Why.
Subtitle: We built Tarka because “high risk” is not an answer — and open, modular software is how you prove one.
-->

Your Fraud Vendor Gave You a Number. Your Customer Asked Why.

*We built Tarka because “high risk” is not an answer — and open, modular software is how you prove one.*

---

The call always seems to land on a Tuesday, well after midnight in some timezone that matters to your biggest account.

Someone important cannot log in, or their transfer is held, or their card suddenly doesn’t work. Support pulls up the tool. The screen shows a score and a label — maybe **High risk**, maybe a band from green to red. They ask engineering what happened. Engineering opens the vendor’s API docs. The payload says **risk_score: 0.94** and little else. Nobody in the room can point to a sentence they would comfortably read aloud to that customer, let alone to a regulator.

I’ve watched good teams eat that cost for years. We started calling it the **fraud tax**: not just the line item on the invoice, but the hours lost to mystery blocks, the goodwill burned on vague explanations, and the slow dread that your controls are something you *buy* but don’t *understand*.

A fair caveat: many vendors now ship **reason codes**, **sandboxes**, or **richer APIs** than a single float. The failure mode we care about is **contractual and operational**—when, in practice, you still can’t answer *why* without a bridge call, or when **your own systems** never retained what you were shown at decision time. A **hybrid** path—**vendor score plus an immutable decision record in your warehouse**—is often the right first step before you change platforms.

**Tarka** is our answer to that tax — not another black box, but a stack you can run, read, and argue with.

## Proof, not performance

The name comes from **tarka** (तर्क) in Sanskrit: a tradition of testing claims with reasons and evidence, not declaring winners by vibe. That sounds philosophical because it is. Fraud is one of the few domains where “trust us” is actively dangerous. If you cannot reconstruct *why* a decision happened, you do not have a control; you have a slot machine with a compliance sticker.

So we designed the core path around something dull and radical: **every evaluate call returns homework**.

Yes, you still get an outcome — allow, review, deny — and a score when you need one. Alongside that, you get structured **inference context**: replay and integrity signals, network trust, geo consistency, velocity, the top reasons that actually moved the needle. You get **tags** your queues and dashboards can filter on without parsing a novel. Your case UI and your API consumers see the same story because we refused to split “what we told the app” from “what we knew internally.”

That choice costs us engineering time. It saves you support time, audit time, and the kind of political capital you spend when the CEO’s friend gets blocked and nobody can explain it.

## Lego, not luggage

We did not ship a single binary that pretends to be your entire risk department. Fraud has natural seams: synchronous scoring at the edge, graph work that wants a different database, ML that wants its own release cadence, investigations that want cases and workflows and humans in the loop.

Tarka is **modular** on purpose. The **Decision API** sits in the middle; graph, ML, case management, streaming ingest, and the rest attach when you are ready — not when the sales cycle says you are. You can start with a **lite** path (decisioning, cases, UI) and grow into rings and models without throwing away your integration.

Open source is part of the same bet. Fraud actors collaborate in the open; the defense side should not be forced to hide behind proprietary walls just to get a production-grade pipeline. If your data never has to leave your VPC, that is not a footnote — it is a design constraint.

## The way we are building it

We are in a **hardening** phase: CI that actually gates merges, security scanning that is boring on purpose, SDKs that match the contract, docs that admit which graph licenses might matter for your legal team. Glamorous posts are easy; trustworthy releases are not.

If you are an engineer, clone the repo, break something, and file an issue with a repro. If you run risk or fraud operations, send this to your tech lead and ask one question: **can our current stack pass the “read it aloud to a customer” test?** If the honest answer is no, you already know why we bothered.

---

**Tarka** — open-source, modular fraud detection.  
Repository: [github.com/pamu512/tarka](https://github.com/pamu512/tarka)

*Optional kicker for your bio line: “Prove every signal.”*
