# Decision → customer journey (action layer)

When evaluate returns `recommended_action`, the merchant app must own the UX. Tarka fires an optional **challenge webhook** (`TARKA_CHALLENGE_WEBHOOK_URL`) for step-up class actions — it does not send SMS/WebAuthn itself.

| Decision / action | Required merchant UX | Tarka side |
|-------------------|----------------------|------------|
| `allow` | Continue checkout / login | Audit + optional graph writeback |
| `review` / `manual_review` | Hold for analyst; show case link | Case creation (non-shadow) |
| `step_up` / soft challenge | WebAuthn / OTP / password re-entry before continue | Webhook `tarka.challenge_webhook/v1` when URL set |
| `block` / hard deny | Hard stop + support copy | Enforcement adapters + audit |
| `payout_hold` | Delay disbursement; notify finance ops | Tags + case priority boost |

## Configure webhook

```bash
export TARKA_CHALLENGE_WEBHOOK_URL=https://merchant.example/hooks/tarka-challenge
export TARKA_CHALLENGE_WEBHOOK_SECRET=...   # optional HMAC hex in X-Tarka-Signature
```

Shadow evaluate (`metadata.shadow=true`) skips challenge dispatch.

See `services/decision-api/src/decision_api/challenge_orchestrator.py`.
