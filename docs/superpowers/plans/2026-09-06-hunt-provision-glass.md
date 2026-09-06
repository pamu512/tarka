# Hunt provision glass Implementation Plan

> **For agentic workers:** User said keep going — implement in this session.

**Goal:** Hunt-off via provision uses the same `isPlaneEnabled("graph")` chrome as an empty graph URL.

**Architecture:** AND `VITE_HUNT_ENABLED` into the graph plane. Product compose bakes it from `TARKA_HUNT_ENABLED`; `up_product.sh` copies `hunt.enabled` when unset.

## Global Constraints

- Do not rebuild Hunt. Do not add a second nav hide.
- Demo compose unchanged. No `:7474` tours.

### Task 1

leanNav tests + `isPlaneEnabled("graph")` hunt flag. Product compose / Dockerfile / `up_product.sh`. Schema description + clone-demo line.
