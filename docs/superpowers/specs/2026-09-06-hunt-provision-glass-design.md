# Hunt provision glass (G-graph1)

**Date:** 2026-09-06  
**Status:** Design locked in gap plan (`keep going`).  
**Branch:** `honesty/hunt-provision-glass` from `origin/master`  
**Related:** `desk_provision.hunt.enabled`, `hunt_enabled()`, `leanNav.ts`

## Goal

`desk_provision` Hunt-off and empty `VITE_GRAPH_SERVICE_URL` both hide Hunt through the same chrome path (`isPlaneEnabled("graph")`). No second nav hide. No stub neighbors.

## Locked

- Do not rebuild Hunt / leanNav path sets.
- Empty plane URL = that plane off.
- Demo compose unchanged.
- No third-party desk names. Do not call Tarka OSS.
- Helm prod-on-k8s keeps frontend OFF — Hunt chrome is the compose desk bake.

## Design

`isPlaneEnabled("graph")` is URL nonempty **and** `VITE_HUNT_ENABLED` not explicitly off (`0` / `false` / `off` / `no`). Unset / empty hunt flag = on (compat).

Product compose bakes `VITE_HUNT_ENABLED` from `TARKA_HUNT_ENABLED`. `make product` copies `hunt.enabled` from the example file into that env when unset.

Loader `hunt_enabled()` already reads `TARKA_HUNT_ENABLED` then `hunt.enabled`. File-only flip without a desk rebuild does not change baked chrome — limitation line says so.

## Non-goals

- New graph SKU. `:7474` tours. GNN. Second `isHuntVisible`.

## Done when

Empty graph URL **or** `VITE_HUNT_ENABLED=0` hide Hunt / leftovers / home `/decisions`. Tests on `leanNav.test.ts`.
