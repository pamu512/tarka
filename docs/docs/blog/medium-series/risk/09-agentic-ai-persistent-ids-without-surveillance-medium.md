**Note:** *I work on [Tarka](https://github.com/pamu512/tarka). The patterns below are product-agnostic; where we ship concrete fields, I point to our docs so you can steal the shape without the repo.*

---

# Agentic AI and Persistent IDs (Without Surveillance)

*Fraud teams need continuity across sessions and tools—not another eternal browser fingerprint.*

---

## The uncomfortable setup

When a user lets an **LLM agent** book travel, move money, or change account settings, the high-level *task* often looks innocent: “buy groceries,” “pay the invoice,” “update my address.” So does the same task when someone is **testing stolen cards** or **driving an account takeover** through automation. Intent at the English layer is a weak fraud signal.

What still works is the older lesson: you score **entities**, **instruments**, and **events**, and you ask whether this action is **coherent** with *this* customer’s history—not whether “shopping” is suspicious.

Agentic AI adds something new: **more programmable surfaces** (tools, MCP servers, plugins) and **faster composition** of steps. That raises the value of **stable identifiers** and **audit-friendly telemetry**. It does *not* automatically justify **surveillance-grade fingerprinting** of every visitor.

This piece is about **persistent IDs that are legitimate**: bound to consent, bound to devices with cryptography where possible, and bound to **your** fraud policy—not to “track everyone better.”

---

## Three different “persistence” problems (do not merge them)

**1) Business identity — “who is the customer?”**  
You already have (or should have) a canonical `**customer_id` / `entity_id`** after onboarding. That is the spine. Everything else hangs off it.

**2) Session and device continuity — “is this the same enrolled client?”**  
Here you want **strong authentication** and **device-bound sessions**, not a grab bag of canvas hashes. Web platform direction (for example **device-bound session credentials**) is about **binding refresh to keys in hardware**, not about giving every site a shared cross-site ID. Mobile has **app attestation** and platform integrity signals under explicit SDK contracts.

**3) Agent runtime — “which software is acting?”**  
This is newer. A sensible pattern is to treat an agent like any other **OAuth client**: a **registered** `client_id`, a published **capability manifest**, scoped tokens, and a server-side `**agent_session_id`** that correlates tool calls. You persist **hashes** of manifests and tool sequences in risk events—not raw prompts—so investigations can explain *what configuration* fired without storing a novel in your transactional log.

If you collapse those three into one “fingerprint,” you get **privacy risk**, **false precision**, and **angry regulators**. If you separate them, you can tune **step-up** and **review** without pretending you read minds from prose.

---

## What “low surveillance” persistence looks like in practice

**Prefer enrollment over inference.**  
A persistent device relationship should often be “**this user enrolled this phone** with passkeys / push / bank app,” not “we guessed it from fonts.”

**Prefer registered agents over anonymous ones.**  
If a payment-critical action arrives with **no** registered client identity and **no** stable device posture, that is a **risk tier** signal—not because automation is evil, but because **unlabeled automation** is what fraud leans on.

**Use correlation, not omniscience.**  
A `**correlation_id`** that ties the browser session, the MCP tool loop, and the authorization attempt is cheap and explainable. It does not require global tracking; it requires **your** services to pass a string you already own.

**Separate “entity graph” from “browser DNA.”**  
Graph analytics still shine when you link **accounts**, **instruments**, and **addresses** with policy and consent. That is a different ethical and legal envelope than extracting stable IDs from incidental signals.

---

## Where agent-specific fields help (and where they do not)

In Tarka we document an optional `**agent_context`** on synchronous evaluate: registered client metadata, optional maker–checker style fields, orchestration digests, and a small **integrity** envelope for upstream heuristics (prompt-injection flags, cross-channel mismatch). Rules see it as structured features; audits can show **what software path** was claimed—without asserting the LLM “meant” anything.

That is **not** a replacement for issuer authentication or 3DS. It is a **layer**: when the instrument and identity story is ambiguous, orchestration and consent metadata help you decide whether to **step up**, **review**, or **block**—especially for **high-value** or **sensitive** mutations.

The limitation stays honest: a patient attacker with a **good** stolen instrument and a **coherent** digital identity can still pass. Agentic AI does not remove that ceiling. It **raises** the return on **strong payment authentication**, **HITL** for sensitive tools, and **clear audit** when automation is in the loop.

---

## A compact policy frame you can reuse

- **Lower agentic risk:** registered OAuth client, manifest matches expectation, device or passkey posture consistent with history, human approval where your policy says so, no injection or cross-channel mismatch flags co-occurring with money movement.  
- **Medium risk:** new client or new manifest for this user, retries and repair loops before pay, untrusted content in context near a payout, VPN without baseline.  
- **Higher risk:** money movement from an unknown client, injection heuristics plus financial mutation in the same trace, permission expansion plus first-time high value, “probe until pay” orchestration patterns.

You can implement that as scores and queues—not as moral panic about AI shopping.

---

## Closing

Persistent identifiers for agentic fraud should answer **accountability** questions: *which client*, *which session*, *which approval path*, *which configuration*. Surveillance answers a different question: *which human across the entire web*, often without proportionate consent.

We can do better than conflating the two. Fraud architecture already knew that **tasks** are not **risks**; agentic AI just makes it obvious again.

**Further reading (Tarka docs):** [Agentic AI fraud detection: variables and layering](../../../guides/agentic-ai-fraud-detection-variables-and-layering.md), [Decision API](../../../services/decision-api.md), [Enterprise Copilot plugin + governance](../../../guides/enterprise-copilot-plugin-and-governance-controls.md), [Investigation Copilot — intended use](../../../guides/investigation-agent-intended-use-and-data-flows.md).

---

*If this helped you draw a line between “bind sessions to devices with consent” and “fingerprint everyone harder,” share it with your privacy and fraud leads in the same meeting.*