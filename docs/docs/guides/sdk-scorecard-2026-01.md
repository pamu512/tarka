# SDK scorecard — calibrated to mid-scale (~3)

**Purpose:** Single place to track **Tarka client SDKs** (web, server, **Android/iOS**) vs typical fraud/device SDKs, with **scores anchored near 3** so gaps read as “next increment,” not exaggerated highs/lows.

**Scale (intentionally tight):**

| Score | Meaning |
|-------|---------|
| **2.0** | Early / partial — usable only with extra glue or narrow scope |
| **2.5** | Credible for pilot — clear limits documented |
| **3.0** | **Default “good OSS integration”** — production-capable with known tradeoffs |
| **3.5** | Strong in dimension — competitive for teams that own the stack |
| **4.0** | Rare — reserved for category-leading *when explicitly validated* |

Peers (Fingerprint-class web, Incognia-class mobile, Sift/SEON-class breadth) are scored on the **same** mid-scale so comparisons stay **directional**, not marketing.

**Repo reality (2026-01):** **`packages/fraud-sdk-typescript`** (web) and **`packages/fraud-sdk-python`** (server) ship; **native** **`packages/fraud-sdk-android`** and **`packages/fraud-sdk-ios`** ship first-party OSS clients (evaluate + `device_context`). See [`sdk-mobile-project.md`](../projects/sdk-mobile-project.md) for deeper attestation parity work.

---

## Dimension scores (target band: **2.8–3.2**)

| Dimension | Tarka Web (TS) | Tarka Server (Python) | Tarka Mobile (Kotlin / Swift) | Peer: Web device ID | Peer: Mobile location | Peer: Platform breadth |
|-----------|----------------|------------------------|--------------------------------|----------------------|-------------------------|---------------------------|
| Browser / client signal breadth | **3.0** | **2.8** (server IP/headers/geo opt-in) | **2.8** (native SDKs + `device_context`) | **3.2** | — | **3.0** |
| Device / session identity | **2.9** (synthetic `device_id`; server fusion expected) | **2.8** | **2.7** | **3.2** | **3.0** | **3.1** |
| Integrity / attestation | **2.9** (challenge + types; app integrates OS APIs) | — | **2.8** | **3.0** | **3.0** | **3.0** |
| Behavioral signals | **3.0** | — | **2.8** | **3.0** | **2.8** | **3.0** |
| Location / geo | **3.0** (opt-in GPS + server IP geo path) | **2.9** | **2.8** | **2.5** | **3.2** | **2.9** |
| Network hardening (pinning, signing) | **2.8** | **2.8** | **2.8** | **2.9** | **2.9** | **3.0** |
| Async / high-volume ingest | **3.0** | **2.9** | **2.8** | **2.8** | **2.8** | **3.1** |
| Typed decision contract (`inference_context`) | **3.2** | **3.0** | **2.9** | **2.8** | **2.8** | **3.0** |

**Row means (approx.):** Tarka Web **~3.0** · Tarka Server **~2.9** · Tarka Mobile **~2.8** · peer columns **~2.9–3.0**.

---

## How to move a row from **2.8 → 3.2** (without rescaling)

- **Identity:** persist server-side entity linking; document `device_id` semantics; optional vendor ID bridge.
- **Mobile:** ship **`fraud-sdk-android` / `fraud-sdk-ios`** with Play Integrity / App Attest wired to `device_context`.
- **Network:** document TLS pinning patterns for high-threat apps; optional signed request helper.
- **Peers:** only bump past **3.2** when a third-party benchmark or procurement checklist justifies it.

---

## Related

- [`sdk-mobile-project.md`](../projects/sdk-mobile-project.md) — mobile gaps and roadmap  
- [`docs/docs/sdks/typescript.md`](../sdks/typescript.md) · [`docs/docs/sdks/python.md`](../sdks/python.md)
