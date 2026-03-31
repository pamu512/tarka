FROM python:3.12-slim
WORKDIR /app
COPY services/feature-service/pyproject.toml /app/
COPY services/feature-service/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "feature_service.main:app", "--host", "0.0.0.0", "--port", "8004"]
