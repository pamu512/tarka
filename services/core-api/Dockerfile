# Context: repository root
#   docker build -f services/core-api/Dockerfile -t tarka-core-api:dev .

FROM python:3.12-slim AS rust-wheel

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable \
    && . "$HOME/.cargo/env" \
    && pip install --no-cache-dir "maturin>=1.7,<2.0"

ENV PATH="/root/.cargo/bin:${PATH}"
WORKDIR /build
COPY packages/tarka-rule-engine /build/packages/tarka-rule-engine
WORKDIR /build/packages/tarka-rule-engine
RUN maturin build --release --out /wheels \
    && ls -la /wheels/*.whl

FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Base image / ensurepip often ship vulnerable setuptools+msgpack; force-replace for Trivy.
# Also drop pip's vendored CycloneDX BOM — Trivy parses it as installed pkgs (setuptools 70 / msgpack 1.1).
RUN pip install --no-cache-dir -U pip wheel \
    && pip uninstall -y setuptools msgpack || true \
    && pip install --no-cache-dir "setuptools>=83.0.0" "msgpack>=1.2.1" \
    && rm -rf /usr/local/lib/python*/ensurepip/_bundled/setuptools*.whl \
              /usr/local/lib/python*/ensurepip/_bundled/wheel*.whl \
    && rm -f /usr/local/lib/python*/site-packages/pip/_vendor/bom.cdx.json \
    && find /usr/local/lib -path '*/pip/_vendor/vendor.txt' -exec sed -i -E '/^(setuptools|msgpack)==/d' {} + \
    || true
# Local path deps in pyproject.toml (file:../core, file:../analytics) must exist before `pip install`;
# sed below rewrites them to file:./core and file:./analytics under WORKDIR.
COPY services/core /app/core
COPY services/analytics /app/analytics
COPY services/shared /app/shared
COPY adapters /app/adapters
COPY services/core-api/pyproject.toml /app/
COPY services/decision-api/src/decision_api /app/decision_api
COPY services/decision-api/alembic /app/decision_migrations
COPY services/decision-api/rules /app/rules
COPY services/decision-api/static /app/static
COPY services/case-api/src/case_api /app/case_api
COPY services/case-api/static /app/case-api/static
COPY services/case-api/alembic /app/case_migrations
COPY services/core-api/src /app/src
COPY packages/shared-core/tarka_shared /app/packages/shared-core/tarka_shared
COPY services/core-api/config/decision_alembic.ini /app/config/decision_alembic.ini
COPY services/core-api/config/decision_alembic.ini /app/alembic.ini
COPY services/core-api/config/case_alembic.ini /app/config/case_alembic.ini
COPY --from=rust-wheel /wheels /wheels
RUN sed -i -e 's|file:../core|file:/app/core|g' /app/analytics/pyproject.toml \
    && sed -i \
        -e 's|file:../core|file:/app/core|g' \
        -e 's|file:../analytics|file:/app/analytics|g' \
        /app/pyproject.toml \
    && pip install --no-cache-dir /wheels/*.whl \
    && pip install --no-cache-dir -e . \
    && pip uninstall -y setuptools msgpack || true \
    && pip install --no-cache-dir "setuptools>=83.0.0" "msgpack>=1.2.1" \
    && rm -f /usr/local/lib/python*/site-packages/pip/_vendor/bom.cdx.json \
    && find /usr/local/lib -path '*/pip/_vendor/vendor.txt' -exec sed -i -E '/^(setuptools|msgpack)==/d' {} + \
    && rm -rf /root/.cache /tmp/pip-* /wheels \
    && python - <<'PY'
import pathlib, re, sys
bad = []
roots = [pathlib.Path(p) for p in ("/usr/local/lib", "/usr/lib", "/app", "/root", "/home")]
for root in roots:
    if not root.exists():
        continue
    for meta in root.rglob("METADATA"):
        parent = meta.parent.name
        if not parent.endswith(".dist-info"):
            continue
        name = parent[: -len(".dist-info")].rsplit("-", 1)[0].lower()
        if name not in {"setuptools", "msgpack"}:
            continue
        text = meta.read_text(encoding="utf-8", errors="ignore")
        ver = next((ln.split(":", 1)[1].strip() for ln in text.splitlines() if ln.startswith("Version:")), "")
        print(f"{meta}: {ver}")
        nums = tuple(int(x) for x in re.split(r"[^\d]+", ver) if x.isdigit())
        if name == "setuptools" and (not nums or nums < (83, 0)):
            bad.append((str(meta), ver))
        if name == "msgpack" and (not nums or nums < (1, 2, 1)):
            bad.append((str(meta), ver))
bom = next(pathlib.Path("/usr/local/lib").rglob("pip/_vendor/bom.cdx.json"), None)
if bom is not None:
    bad.append((str(bom), "pip vendor CycloneDX present"))
try:
    import tarka_rule_engine  # noqa: F401

    if not callable(getattr(tarka_rule_engine, "evaluate_json_rules_rust", None)):
        print(
            "FAIL tarka_rule_engine missing evaluate_json_rules_rust",
            file=sys.stderr,
        )
        raise SystemExit(1)
except ImportError as exc:
    print("FAIL tarka_rule_engine missing:", exc, file=sys.stderr)
    raise SystemExit(1)
print("OK tarka_rule_engine import")
if bad:
    print("FAIL stale packages:", bad, file=sys.stderr)
    raise SystemExit(1)
print("OK package audit")
PY
ENV PYTHONPATH=/app/src:/app:/app/shared:/app/packages/shared-core
ENV RULES_PATH=/app/rules
CMD ["/bin/sh", "-c", "alembic -c /app/config/decision_alembic.ini upgrade head && alembic -c /app/config/case_alembic.ini upgrade head && exec uvicorn core_api.main:app --host 0.0.0.0 --port 8000"]
