# Borrowing mature OSS patterns (Tazama, Marble, Jube, …)

Tarka’s **30/60/90** plan and **`borrowed-from-OSS`** GitHub theme emphasize **accelerating maturity** by adopting **battle-tested ideas** — not copying trademarks or stripping attribution.

## Principles

1. **License compatibility** — Prefer **Apache-2.0** / **MIT** patterns; respect **copyleft** if you embed code (see root **`LICENSE-DEPENDENCIES.md`**).
2. **Credit in code and docs** — Module docstrings, `NOTICE`, or `docs/docs/guides/` references with **upstream URL** and **commit/version** when porting logic.
3. **Isolate boundaries** — Typology processors, rule DSL parsers, and ML calibration should live in **clear packages** (`packages/` or `services/*/src/...`) with tests so upstream upgrades do not blur into core APIs.

## Execution order

Use **[oss-ship-order-dependencies.md](./oss-ship-order-dependencies.md)** and **`scripts/release/release-queue-2026-05.json`** (or current queue) for **issue ordering**. Link new work to **v1.2.0** (vertical packs, benchmarks) and **v1.3.0** (governance / evidence) as appropriate.

## Concrete integration surfaces in this repo

| Upstream theme | Tarka landing zone |
|----------------|-------------------|
| **Typology processors** | `decision-api` rule packs / vertical packs (`vertical_packs.py`) + simulation benchmarks |
| **Rule DSL / policy** | `json_rules` + future OPA templates (`roadmap-30-60-90.md` Epic D) |
| **Adaptive / streaming ML** | `ml-scoring` adaptive detector + ONNX path |
| **Graph / entity resolution** | `graph-service` + case graph endpoints |

## What “done” looks like

- Exported **benchmark delta** or **parity test** vs a frozen fixture set.
- **Documentation** of what was borrowed, what was reimplemented, and **migration** notes for operators.
