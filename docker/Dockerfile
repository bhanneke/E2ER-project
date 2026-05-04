FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg3 and sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[pgvector]"

COPY src/ src/
COPY sql/ sql/
COPY skills/ skills/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8280", "--workers", "1"]
