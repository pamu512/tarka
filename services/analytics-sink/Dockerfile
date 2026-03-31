FROM python:3.12-slim
WORKDIR /app
COPY services/analytics-sink/pyproject.toml /app/
COPY services/analytics-sink/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "analytics_sink.main:app", "--host", "0.0.0.0", "--port", "8008"]
