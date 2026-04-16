# Integrity policy matrix (reference)

Maps **platform** (from `device_context.platform`) to expectations used by `decision_api.integrity_policy`:


| Platform  | Signals that reduce trust when present                             | TLS pinning (`metadata.tls_pinning_verified`)         |
| --------- | ------------------------------------------------------------------ | ----------------------------------------------------- |
| `web`     | (none extra beyond core tamper/network heuristics)                 | `true` +0.05 to `integrity_confidence`; `false` −0.08 |
| `android` | `sdk:repackaged`, `sdk:emulator` → `integrity:`* supplemental tags | same                                                  |
| `ios`     | same as android                                                    | same                                                  |
| `server`  | no platform-specific supplemental tags                             | same                                                  |


Supplemental tags are merged into `signal_tags` before `inference_context` is built so `top_signals` and tiering stay consistent.

This document is normative for **code** in `services/decision_api/integrity_policy.py`; update both together.