FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/graphql-gateway/pyproject.toml /app/
COPY services/graphql-gateway/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "graphql_gateway.main:app", "--host", "0.0.0.0", "--port", "8010"]
