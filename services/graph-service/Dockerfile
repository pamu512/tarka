FROM python:3.12-slim
WORKDIR /app
COPY services/graph-service/pyproject.toml /app/
COPY services/graph-service/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "graph_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
