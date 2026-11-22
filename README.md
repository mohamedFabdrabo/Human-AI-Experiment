# Experiment platform

The backend loads experiment configuration, initializes the database schema,
and creates an experiment with three participant slots. `POST /join` assigns
an available human slot. The backend lifecycle starts when all humans join,
runs two timed discussions and voting rounds, and computes final results.
The WebSocket backend supports state updates, discussion messages and voting;
the frontend provides the waiting room, discussion, voting and results screens.

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
read-only; restart the backend after changes. Participant types remain server-side.

## Run locally

With Docker and Docker Compose installed and Docker running:

```sh
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend health check: http://localhost:8000/health (returns `{"status":"ok"}`)

The backend permits browser `POST /join` requests from the local frontend
origins `http://localhost:5173` and `http://127.0.0.1:5173`. Other frontend
origins need appropriate CORS configuration or a same-origin proxy.
The frontend development server proxies `/join` and `/ws` to the backend.

Compose starts PostgreSQL with a named `postgres_data` volume and waits for
its health check before starting the backend. The backend health endpoint only
checks that the API is running; it does not check the database. Database
credentials in the Compose file are for local development only. The backend
creates missing tables on startup and adds the lifecycle deadline column to
databases created before it was introduced. Other schema changes require
manual migrations.
Each backend startup creates a new waiting experiment and three slots using
the current configuration. Earlier records remain in the database, but are
not resumed.

`POST /join` accepts `{}` and returns a player label and private participant
token, or HTTP 409 when all human slots are taken. Tokens and slot assignments
are kept in memory and are lost on restart. The application runs as a single
backend process; do not share participant tokens.
Connect to `/ws?token=<participant_token>` for the events described in the
[communication contract](docs/design/communication-contract.md). The backend
removes the query string before Uvicorn's handshake log, but reverse proxies
must also be configured not to log WebSocket query strings. Avoid server or
WebSocket-library trace/debug logging that records request URLs. Use HTTPS/WSS
outside local development.

The lifecycle service validates transitions and votes within the caller's
database transaction. Discussions end after the configured duration (checked
once per second); voting waits for all three participants. Each AI participant
sends one scripted message at the start of each discussion and automatically
votes for Player A, including themselves if applicable. Only
round-two votes determine the result, with ties broken in A, B, C order.
The next discussion starts when the last round-one vote is accepted. No
voting timeout or recovery of an interrupted experiment is implemented.
The scripted AI behavior is isolated in `backend/ai/scripted.py`. WebSocket
updates are sent directly to each connection, so a slow connection can delay
other updates.

Stop the services with `docker compose down`. The named volume is retained
across restarts.

## Backend tests

With the database running, execute the PostgreSQL-backed tests in an isolated
transaction:

```sh
docker compose run --rm --build backend python -m pytest
```
