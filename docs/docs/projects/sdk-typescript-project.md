# TypeScript SDK Project

## Scope

Browser/server JS client, device signal collection, attestation flow, and typed response models.

## Current Gaps

- Inference contract parity has started but UI/runtime safety can be deeper.
- Runtime mode clarity (browser vs server) needs stronger guardrails.

## Roadmap

### Now

- Maintain strict response typing with `inference_context`.
- Ensure collectors and decision client fail gracefully by runtime environment.

### Next

- Add signed payload envelope support and replay-oriented metadata.
- Add stronger type-safe helpers for explainability and inference rendering.

### Later

- Split platform-specific entry points with dedicated build targets.
