FROM python:3.12-slim
WORKDIR /app
COPY services/ml-scoring/pyproject.toml /app/
COPY services/ml-scoring/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src
ENV DISABLE_ML=false
CMD ["uvicorn", "ml_scoring.main:app", "--host", "0.0.0.0", "--port", "8005"]
