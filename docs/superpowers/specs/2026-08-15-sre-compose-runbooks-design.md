# SRE Compose runbooks (leave the lab)

**Date:** 2026-08-15  
**Status:** Implemented  
**Approved:** Linux VM + Compose is the production default.

## Goal

An on-call engineer can bring up, size, and page Tarka from Compose profiles on Linux. Apple SKUs are not a requirement.

## Shape

- New runbook: `docs/docs/operations/sre-compose-profiles.md`
- Fill `runbook-pack-index.md`
- README / VISION / INDEX / mkdocs point at the runbook
- RAM numbers are planning floors from existing desk docs, not SLOs

## Out of scope

Helm as default, new alerts, new compose files.
