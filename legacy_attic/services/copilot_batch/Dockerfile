# Build context: repository root.
FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY legacy_attic/services/copilot_batch/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY legacy_attic/services/copilot_batch/main.py .

CMD ["python", "-u", "main.py"]
