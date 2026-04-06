# Saarthi Pro agent — container distribution

Ships the **investigation copilot** as a single OCI image built from this monorepo (`services/investigation-agent` + `services/shared`). Use for **Saarthi Pro** releases, air-gapped builds, or as the source layout when mirroring into the [Saarthi-pro](https://github.com/pamu512/Saarthi-pro) repository.

**CI:** GitHub Actions job **`docker-build-saarthi-pro-agent`** (`.github/workflows/ci.yml`) builds this Dockerfile on every push/PR after `lint`, `test-investigation-agent`, and `test-investigation-agent-golden-matrix` pass. `INTEGRATION_CONTRACT_VERSION` for image labels is parsed from `integration_contract.py` so label drift is caught if the file changes without updating the Dockerfile default.

## Build (from fraud-stack root)

```bash
export VER=0.1.0
export SHA=$(git rev-parse HEAD)
docker build -f distributions/saarthi-pro-agent/Dockerfile \
  --build-arg SAARTHI_PRO_VERSION="$VER" \
  --build-arg FRAUD_STACK_GIT_SHA="$SHA" \
  --build-arg INTEGRATION_CONTRACT_VERSION=1.1.0 \
  -t saarthi-pro-agent:${VER} .
```

Set **`INTEGRATION_CONTRACT_VERSION`** to match `INTEGRATION_CONTRACT_VERSION` in `services/investigation-agent/src/investigation_agent/integration_contract.py` at this commit.

Windows: `scripts/build_saarthi_pro_agent_image.ps1` (from repo root).

## Runtime provenance

- Set **`AGENT_BUILD_ID`** to the image digest or tag (e.g. `sha256:…` or `saarthi-pro-agent:0.1.0`); it appears in **`evidence_bundle_draft.agent_build`** when using v1/dual bundle format.
- Set **`INTEGRATION_PROFILE_ID`** per [adapter catalog](../../docs/docs/guides/saarthi-pro-adapter-catalog-and-certification.md).

## Smoke

```bash
docker run --rm -p 8006:8006 \
  -e CASE_API_URL=http://host.docker.internal:8002 \
  -e DECISION_API_URL=http://host.docker.internal:8000 \
  -e AGENT_BUILD_ID=local-smoke \
  saarthi-pro-agent:0.1.0
curl -s http://localhost:8006/v1/health | jq .integration.contract_version
```

## Release record

Copy [RELEASE.md](RELEASE.md) into the consumer repo (e.g. Saarthi-pro) and update per tag. See [Saarthi Pro standalone distribution layout](../../docs/docs/guides/saarthi-pro-standalone-distribution-layout.md).

## Compose (optional)

From repo root:

```bash
docker compose -f distributions/saarthi-pro-agent/docker-compose.example.yml up --build
```

Edit env files or overrides for your upstream URLs.
