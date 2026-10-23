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

Inside the container the server binds `0.0.0.0:8280` (a port mapping cannot reach 127.0.0.1 in a
container); `docker-compose.yml` publishes it on the host's `127.0.0.1:8280` only. Keep that
mapping: `8280:8280` would put the dashboard on every network the computer is on. Because the
server listens on every interface of the container, the entrypoint refuses to start without
`API_AUTH_TOKEN` in `.env`; every API request then needs `Authorization: Bearer <token>`. The
server answers only to a `Host` of 127.0.0.1, localhost or [::1]; list other names (a reverse
proxy's) in `E2ER_ALLOWED_HOSTS`, comma-separated.
