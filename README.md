# Human-AI Experiment

A three-player experiment with two timed discussions and a vote after each
round. The app uses React, FastAPI, and PostgreSQL.

## Run the app

Install Docker and Docker Compose, then run:

```sh
docker compose up --build
```

Open [http://localhost:5173](http://localhost:5173) in a separate browser tab
for each human participant and select **Join experiment**. Once everyone has
joined, discuss and vote in each round to see the final result.

To stop the app, run `docker compose down`. The database volume is retained.

## Configuration

Edit `config.yml` to choose the three participants and discussion duration:

```yaml
participants: [human, ai, ai]
rounds: 2
discussion_duration_seconds: 60
```

Supported conditions are `[human, human, human]`, `[human, human, ai]`, and
`[human, ai, ai]`. The order assigns player labels A, B, and C. There must be
at least one human, exactly two rounds, and a positive discussion duration.
After changing the configuration, start a new experiment with:

```sh
docker compose up -d --force-recreate backend
```

## Design decisions

- Participants see only neutral player labels, not human or AI types.
- Each AI sends one scripted message at the start of each discussion and
  automatically votes for Player A. Self-voting is allowed.
- Voting waits for all three participants. Round-one results are hidden;
  round-two votes determine the Decision Maker. Ties are broken in A, B, C order.
- One experiment runs at a time. Restarting the backend starts a new experiment;
  previous database records remain, but interrupted experiments are not resumed.
  Reconnection and voting timeouts are not implemented.

Run backend tests with `docker compose run --rm --build backend python -m pytest`.
