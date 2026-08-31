# Tarka buyer demo — 5 minutes (read this)

Desk: http://127.0.0.1:3000 · tenant `demo` · Continue to desk

Print this or keep it on a second screen. Bold lines are what you say. Everything else is you, not them.

Clock starts only after a hard-refresh on Hunt shows a Person evaluate wrote:

`http://127.0.0.1:3000/graph?entity_id=hunt-eval-buyer&tenant_id=demo`

You must see:
- Person `hunt-eval-buyer` in the dossier
- Device `hunt-eval-device` on a `USED_DEVICE` link
- Story on the pane: newest first, Hold on its clock, FLAG/deny why still expanded
- evaluate receipt id on the link row

If the Person is missing, or Hunt is empty, do not start. Rebuild first or cancel.

A second Person (`hunt-eval-peer`) shares that Device. Search `hunt-eval-device` or click the Device to show both. If only one Person is on the Device, do not narrate who-else.

`device_signals` as seeded is FLAG/review (VPN + automation; rooted may be present). Deny is score ≥ 80. Say FLAG or review, matching the pane. Never say DENY unless the pane literally says deny.

---

## Do not click

Decisions table row · Advise · Observe · Visual builder · Disputes · QA · + New Case · File Dispute · Resolve · Compare · Advanced · Sign out

## Do not say

“AI decided.” · “our model” · “Azure wrote this.” · “AI-authored” · “Shadow” · a review % · DENY (unless the pane is deny) · `Auto: deny login`

If they ask Advise / Observe: “That plane is off. Empty URL. We do not mock it.”

If they ask Decisions: “Receipts are a plane. The job is this Person.”

---

## 0:00–0:45  Speak (laptop already on Hunt)

Do not click. Cursor in the corner.

**Fraud vendors sold you a cloud score. You send them the event, they send back blocked, and ops reconstructs a why that should have been on the object. That is a ticket product with a model behind it.**

**Tarka is a local-first fraud OS. You own the JSON pack. Evaluate runs on metal you control. Every event writes a Person, a Device, a Payment or Login, and typed links. We do not ship a Tarka model. You bring Azure, Vertex, Bedrock, or vLLM when you want an LLM. Advise is off today.**

**The desk opens on the Person. Receipts stay a plane. A leftover case is not intake.**

---

## 0:45–2:15  Hunt (point, then one click)

Stay on Hunt. Point at **Person hunt-eval-buyer**. Point at **USED_DEVICE → hunt-eval-device**.

**Same person, two events. Evaluate wrote this object. The payment and the login are facts on the Person, not a queue of tickets.**

Point at **Story**. Newest first. Hold is an event on the Person, not a badge you go find on Cases. FLAG/deny still has `device_signals` why. Then the receipt id on the link.

**You do not reconstruct evaluate → hold → next evaluate. The Person already is that story.**

Click **hunt-eval-device**. Hunt re-seeds. You should see both Persons if the peer evaluate ran.

**Who else used this device. Click the Person to come back.**

If they ask to open Decisions:

**That is the receipt stream. I am not going there. The why is on this object.**

If they ask who decided:

**The JSON pack. Rust evaluate. Not a model.**

Do not add a third event. Do not quote a review rate.

---

## 2:15–3:45  Hold

On the Person pane: **Hold this person**. Wait for Held. Point at **Hold · held** on the dossier.

**Hold is a verb on the Person. It writes back. The leftover case is the same object. I did not open Cases to do this.**

If they ask who wrote the pack: left nav → **Rules**. Open live `device_signals` JSON. Do not click + Create, Save, Templates, canvas, promote, or toggle a rule.

**This is the live pack. JSON. Humans own it. This is not an AI-authored rule.**

Then leave the canvas. Back to Hunt on `hunt-eval-buyer`.

If Advise tabs are visible, do not click them.

---

## 3:45–5:00  Close (spoken)

Hunt search box: type `buyer@desk.example` (or `+15550199`). Point at Person `hunt-eval-buyer` and the `email` / `phone` chip. Then type `hunt-eval` if you need the prefix beat. Do not wander. Left nav is Hunt, not Cases.

**Find the Person from an email or a phone. You are not scrolling a ticket inbox.**

**If an analyst disagrees, they change the decision and type why. We store that as a label so the next evaluate can learn. Hold already wrote a fact on this Person.**

**What you just saw is the core. Evaluate writes objects. Hunt is the job. Hold writes back. Receipts, Advise, and Observe stay planes. Advise is off. We do not mock it.**

**The add-on we will not demo until it is real: a scout writes a rule, parks it in Observe, and either the gates promote it or a human does. You still own the live pack. Evaluate stays Rust.**

Hands off the keyboard. Stop on Hunt.

---

## If they ask

| They say | You say |
|---|---|
| Review rate / % blocked | We do not quote one. It depends on the pack and the traffic. |
| Chargebacks | One late label. Not the product. |
| Your model | There isn’t one. BYO LLM, in-tenant preferred. Off today. |
| Shadow | Observe is canary evaluate. Advise is optional LLM. Both off today. |
| Saarthi | Removed. Not a product. |
| Can we see the rule? | `/rules` live `device_signals` JSON. Read-only. Leave the canvas. |
| Decisions / receipts | A plane. The job is the Person. |
| Cases / the queue | Leftover from Hold. Not in the left nav. Do not open it. |
| Advise / Observe | Plane is off. We do not mock it. |
| Visual builder | Stretch. Not this desk. |
| AI wrote this / Vertex | Not this pack. `device_signals` is human-owned. We will not caption it as AI. |
| Why not DENY? | The pack scored review, not deny. Deny is a higher gate. We did not bump the seed. |

---

## Cheat card (fold this)

1. Hunt on `hunt-eval-buyer`. Speak the punchline. Point Person, Device, pack-why, receipt on the edge.
2. Click Device. Two Persons if the peer is there. Back to the Person.
3. Hold this person. Point held.
4. If asked: Rules → `device_signals`. Leave.
5. Search `hunt-eval`. Stop on Hunt.

Rebuild lite + fraud-desk (graph-service + core-api green) before Thursday or cancel.
