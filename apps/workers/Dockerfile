FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY worker ./worker
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

CMD ["python", "-m", "worker.main"]
