<!--
MEDIUM PUBLISHING
Title:    We Built an AI Copilot for Fraud Investigations, Not an Autopilot
Subtitle: Demos love autonomous agents. Production fraud needs someone who can say no — and software that doesn’t pretend it already did.
-->

We Built an AI Copilot for Fraud Investigations, Not an Autopilot

*Demos love autonomous agents. Production fraud needs someone who can say no — and software that doesn’t pretend it already did.*

---

If you’ve sat through a vendor pitch in the last two years, you’ve seen the slide: an **AI agent** that “handles” investigations end to end—triage, evidence, maybe even the disposition. The demo is smooth. The room nods.

Then someone who actually runs fraud ops asks a quiet question: **Who signs the SAR? Who explains the false positive to legal? Who gets deposed if the model “decided” wrong?**

We designed **Tarka’s investigation side** around a different default. The service we call **Saarthi** (the investigation agent) is a **copilot**: it helps a human **query** cases, **pull** graph and audit context, **draft** labels or notes—but it does not replace the analyst as the accountable party. We did not ship an autonomous decision-maker dressed up as “efficiency,” and that was deliberate.

## What demos optimize vs what operations owe

Autonomy demos optimize for **wow**. They compress a multi-step investigation into a single glowing transcript.

Real investigations optimize for **defensibility**. You need **traceable** steps: which record was read, which rule fired, which graph path was considered, what the human **chose** to accept or reject. Regulators and civil discovery do not care how confident the model sounded; they care what **your organization** did with **verifiable** artifacts.

A copilot fits that shape. An opaque agent that “closed” cases does not.

## Fraud is a high-stakes domain for wrong tools and wrong certainty

Large language models are strong at language and weak at **knowing when they must stop**. In our own project notes we track risks that are boring to tweet about but deadly in production: **wrong tool selection**, **JSON truncation**, **narratives that sound authoritative but aren’t mechanically verified** against source systems.

If you give that stack **write authority** over production outcomes—auto-deny, auto-close, auto-SAR—you are one bad afternoon away from a **systematic** error, not a one-off typo.

A copilot architecture keeps the **tools** (case API, graph service, decision audit, replay) **explicit**. The model proposes; **systems of record** answer; the human **commits** when the workflow requires it. That is slower than a keynote. It is faster than a lawsuit.

## Trust is asymmetric

Customers and boards trust **humans with job titles** to explain trade-offs. They are rightly suspicious of **vendors who promise full automation** in a domain where labels are noisy, chargebacks arrive late, and “ground truth” is a moving target.

We are not anti-ML. We run scoring and features where **measurement** and **rollback** are possible. The investigation agent is where we draw a bright line: **assist, don’t usurp**. Your fraud lead should still be able to say, without irony, **“I approved that disposition.”**

## What “copilot” means in our stack (concretely)

Saarthi is an **LLM with a tool-use loop** against real services: cases and disputes, graph queries, decision audit and entity velocity, paired replay when **trace IDs** line up. The direction of travel in our roadmap is **more deterministic traces**, **tighter alignment with evidence bundles**, and **policy-safe defaults**—not “remove the human from the loop.”

We even phrase future work honestly: **semi-autonomous triage** only makes sense with **strict human-in-the-loop boundaries**, not as a rebranded autopilot.

## When autonomy might belong (later, and fenced)

There are places autonomy can help: **routing drafts**, **suggesting next queries**, **clustering similar cases for review**—always with **thresholds**, **shadow mode**, and **kill switches**. The product mistake is selling **stage-one demos** as **stage-four accountability**.

If you are evaluating a fraud “AI agent,” ask your vendor the same question you’d ask a new analyst: **What are you not allowed to do without a second signature?** If the answer is “everything, we’re end to end,” keep your checkbook closed until the architecture catches up to the brochure.

## Closing

We chose a **copilot** because fraud investigations are **judgment under uncertainty**, not a speedrun. The goal is **analyst leverage** with **institutional memory** in the APIs and databases—not a chat window that **pretends** it already ran your program.

If you want to see how we wire the loop today: **[Tarka on GitHub — investigation-agent](https://github.com/pamu512/tarka)** (service under `services/investigation-agent`; module codename **Saarthi** in `tarka.py` and `docs/docs/guides/module-codenames.md`). For a **commercial** distribution of the same copilot—support, procurement-friendly packaging, optional **maintained adapters**—see **[Saarthi Pro](https://github.com/pamu512/Saarthi-pro)** and the in-repo comparison **[Saarthi Pro vs OSS](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/saarthi-pro-vs-oss.md)**. Scope, shipped features, and honest limits for the open reference: [investigation-agent project](https://github.com/pamu512/tarka/blob/master/docs/docs/projects/investigation-agent-project.md).

---

**Suggested Medium topics:** Artificial Intelligence, Fraud Prevention, Cybersecurity, Software Engineering, Risk Management

**Companion pieces:** `engineering/02-inference-context-contract.md` (structured proof on the evaluate path); `risk/01-beyond-the-black-box-score.md` (accountability for decisions).
