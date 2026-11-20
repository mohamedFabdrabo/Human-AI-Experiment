# Experiment platform

The backend loads experiment configuration, initializes the database schema,
and creates an experiment with three participant slots. `POST /join` assigns
an available human slot; the remaining experiment flow and WebSockets are not
implemented yet.

## Experiment configuration

The root `config.yml` defines the participant types, number of rounds, and
discussion duration in seconds. To select a condition, set `participants` to
one of:

- `[human, human, human]`
- `[human, human, ai]`
- `[human, ai, ai]`

The backend loads the file at startup. It requires exactly three participants,
at least one human, exactly two rounds, and a positive integer duration.
Invalid or missing configuration prevents startup. Compose mounts the file
read-only; restart the backend after changes. Experiment behavior is not yet
implemented. Participant types remain server-side.

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
credentials in the Compose file are for local development only. The backend
creates missing tables on startup; this does not migrate an existing schema.
Each backend startup creates a new waiting experiment and three slots using
the current configuration. Earlier records remain in the database, but are
not resumed.

`POST /join` accepts `{}` and returns a player label and private participant
token, or HTTP 409 when all human slots are taken. Tokens and slot assignments
are kept in memory and are lost on restart. The application runs as a single
backend process; do not share participant tokens.

Stop the services with `docker compose down`. The named volume is retained
across restarts.

## Backend tests

With the database running, execute the PostgreSQL-backed tests in an isolated
transaction:

```sh
docker compose run --rm --build backend python -m pytest
```
