FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/integration-ingress/pyproject.toml /app/
COPY services/integration-ingress/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
CMD ["uvicorn", "integration_ingress.main:app", "--host", "0.0.0.0", "--port", "8003"]
