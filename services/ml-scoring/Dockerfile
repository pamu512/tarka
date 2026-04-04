FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/ml-scoring/pyproject.toml /app/
COPY services/ml-scoring/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
ENV DISABLE_ML=false
CMD ["uvicorn", "ml_scoring.main:app", "--host", "0.0.0.0", "--port", "8005"]
