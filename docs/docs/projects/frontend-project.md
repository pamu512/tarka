# Frontend Project

## Scope

Analyst UX across dashboard, cases, graph explorer, explainability, and operations pages.

## Testing

From `frontend/`: **`npm run test`** runs **Vitest** (jsdom + Testing Library) against selected UI surfaces (e.g. trust/ops readiness). **`npm run build`** runs `tsc -b` and the Vite production bundle. CI runs both in that order after `npm ci` (see `.github/workflows/ci.yml`, `build-frontend` job).

## Current Gaps

- Inference metrics are only partially surfaced across views.
- KPI benchmarking and workflow confidence cues can be stronger.

## Roadmap

### Now

- Surface normalized inference context in core analyst decision views.
- Improve explainability readability with consistent risk metric presentation.

### Next

- Add dashboard-level inference trend views and replay-risk monitoring.
- Add benchmark overlay cards tied to release and model changes.

### Later

- Guided analyst copilot panels for next-best-actions and evidence trails.