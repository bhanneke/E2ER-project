# Optional Postgres stack (development)

Not needed to use e2er. e2er stores studies in SQLite at `~/.e2er/papers.db` and needs no
database server; the replication template's sandbox does not use this folder either (it starts
its own containers).

`docker-compose.yml` starts Postgres with pgvector, for development on the Postgres code path
and for the pgvector literature knowledge base:

```bash
docker compose -f docker/docker-compose.yml up -d db
export DATABASE_URL=postgresql://e2er:e2er_dev@127.0.0.1:5439/e2er_v3
python scripts/migrate.py
```

The `app` service builds e2er from this checkout into a container. It is kept for reference and
is not tested; install e2er with `uv tool install e2er` or `pip install e2er` instead.
