# Build context: repository root.
FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY services/copilot_batch/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/copilot_batch/main.py .

CMD ["python", "-u", "main.py"]
