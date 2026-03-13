FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY runner ./runner
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

CMD ["python", "-m", "runner.main"]
