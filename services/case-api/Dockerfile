FROM python:3.12-slim
WORKDIR /app
COPY services/case-api/pyproject.toml /app/
COPY services/case-api/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "case_api.main:app", "--host", "0.0.0.0", "--port", "8002"]
