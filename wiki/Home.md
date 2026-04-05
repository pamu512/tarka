# Tarka Wiki

Welcome to the Tarka wiki.

## Executive Pitch

Tarka helps organizations reduce fraud losses while improving customer trust by unifying real-time decisioning, investigations, and compliance evidence in one platform. Instead of stitching together disconnected tools, teams get a single, auditable operating layer for rules, machine learning, graph intelligence, and third-party integrations, so risk teams move faster, engineering teams stay in control, and leadership gets clearer visibility into fraud outcomes and operational performance.

## Who Tarka Is Aimed At

- Fintech, payments, lending, crypto, and marketplace teams with meaningful fraud pressure.
- Risk, fraud, and operations organizations that need both real-time controls and investigation workflows.
- Compliance-driven teams that must prove why decisions were made and how controls are governed.
- Engineering teams that want open, modular architecture instead of black-box vendor lock-in.

Tarka is an open, modular fraud decisioning stack with:
- Decision engine (rules + ML + policy)
- Graph intelligence (entity links and tags)
- Investigation and case management
- SDKs (Python, TypeScript, Android, iOS)
- Streaming, analytics, and compliance tooling
- One-click Integration Hub (20 providers, category filtering, health checks)
- Multi-cloud vault KMS support (AWS, GCP, Azure, local fallback)

## Start Here

- [Quickstart](Quickstart)
- [Architecture](Architecture)
- [Services](Services)
- [Rules and Simulation](Rules-and-Simulation)
- [Security and Compliance](Security-and-Compliance)
- [Operations](Operations)
- [Who Should Choose Tarka](Who-Should-Choose-Tarka)

## New in Current Build

- One-click integrations support **either `api_key` OR `username` + `password`**.
- Vault-backed masked credential storage for integrations.
- KMS encryption providers: `local`, `aws`, `gcp`, `azure`.
- Rotation management endpoints and operator visibility for recent KMS rotation jobs.
- CodeQL advanced workflow now uses manual build handling for compiled languages and Node 24 action runtime compatibility.

## Repository

- Source code: `pamu512/tarka`
- Latest patch: **`v1.0.2`** (`docs/docs/releases/v1.0.2.md` on default branch): CodeQL + security scan **`workflow_dispatch`**, Swift SPM/CodeQL build fixes, Trivy SARIF upload v4, drift score smoke, Docker base refresh.
