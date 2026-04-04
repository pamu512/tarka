FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/case-api/pyproject.toml /app/
COPY services/case-api/alembic.ini /app/
COPY services/case-api/alembic /app/alembic
COPY services/case-api/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
CMD ["uvicorn", "case_api.main:app", "--host", "0.0.0.0", "--port", "8002"]
