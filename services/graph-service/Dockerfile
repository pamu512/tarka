FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/graph-service/pyproject.toml /app/
COPY services/graph-service/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
CMD ["uvicorn", "graph_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
