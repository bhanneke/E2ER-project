FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg3, sentence-transformers, and the htmx vendor curl.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[pgvector]"

COPY src/ src/
COPY sql/ sql/
COPY skills/ skills/
COPY scripts/ scripts/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh scripts/vendor_htmx.sh

# Vendor htmx at build time so the static asset is in the image (avoids a
# runtime fetch in airgapped environments).
RUN bash scripts/vendor_htmx.sh || echo "htmx vendor failed at build; entrypoint will retry"

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
EXPOSE 8280

# Healthcheck — used by docker compose to gate dependents.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD curl -fsS http://localhost:8280/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
