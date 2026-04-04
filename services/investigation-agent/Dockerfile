FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pip -U
COPY services/investigation-agent/pyproject.toml /app/
COPY services/investigation-agent/src /app/src
COPY services/shared /app/shared
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app/src:/app/shared
CMD ["uvicorn", "investigation_agent.main:app", "--host", "0.0.0.0", "--port", "8006"]
