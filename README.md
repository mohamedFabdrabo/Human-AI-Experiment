# Experiment platform

This is the initial project skeleton. The experiment flow, configuration
loading, database entities, and communication contract are not implemented yet.

## Experiment configuration

The root `config.yml` defines the participant types, number of rounds, and
discussion duration in seconds. To select a condition, set `participants` to
one of:

- `[human, human, human]`
- `[human, human, ai]`
- `[human, ai, ai]`

Compose mounts the file read-only into the backend. The backend does not read
or enforce it yet; changing it currently has no effect on the skeleton.

## Run locally

With Docker and Docker Compose installed and Docker running:

```sh
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend health check: http://localhost:8000/health (returns `{"status":"ok"}`)

Compose starts PostgreSQL with a named `postgres_data` volume and waits for
its health check before starting the backend. The backend health endpoint only
checks that the API is running; it does not check the database. Database
credentials in the Compose file are for local development only. No database
tables are created by the application yet.

Stop the services with `docker compose down`. The named volume is retained
across restarts.
