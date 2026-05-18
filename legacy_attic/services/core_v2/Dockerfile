# Build context: repository root (``docker build -f services/core_v2/Dockerfile .``).
FROM python:3.11-slim-bookworm AS rust-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /src
COPY legacy_attic/services/core_v2/requirements.txt /src/requirements.txt
RUN pip install --no-cache-dir maturin==1.13.1

COPY legacy_attic/services/core_v2/rust_engine /src/rust_engine
WORKDIR /src/rust_engine
RUN maturin build --release -i python3.11

FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY legacy_attic/services/core_v2/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=rust-builder /src/rust_engine/target/wheels/ /wheels/
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

COPY legacy_attic/services/core_v2/*.py .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
