# Enforcement notify provision Implementation Plan

> **For agentic workers:** User said `go` — implement in this session (executing-plans + TDD).

**Goal:** Provision hook URLs; product observe inbox in Postgres; allow webhook confirmed.

**Architecture:** Loader grows hook/store helpers. Enforcement and observe_notify call them. New `observe_notify` table. File store remains the demo default.

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- Empty hook URL = sink off. Secrets never in the provision file.
- No `friction_tier`. No LISTEN/NOTIFY. `make demo` unchanged.

### Task 1: Loader hooks + store (TDD)

`services/shared/desk_provision.py` + `test_desk_provision.py`

### Task 2: Wire enforcement + observe file path still works

`enforcement.py`, `observe_notify.py`, allow webhook test

### Task 3: Postgres observe inbox

Model + Alembic `observe_notify`. Store switch. Tests on sqlite file as stand-in.

### Task 4: Schema, Helm, docs, PR

Schema/example/Helm hooks. decide-to-act + README. PR into `#385`.
