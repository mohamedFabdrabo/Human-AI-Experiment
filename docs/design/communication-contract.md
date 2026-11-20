# React–FastAPI Communication Contract

This is a minimal implementation choice based on the [blueprint](./implementation-blueprint.md) and [database design](./database-schema.md), not an API prescribed by the assessment. One experiment runs at a time. JSON is used for REST and WebSocket messages.

## 1. REST: join the experiment

### `POST /join`

Request:

```json
{}
```

Success: `201 Created`

```json
{
  "player": "A",
  "participant_token": "opaque-random-token"
}
```

The server assigns a human slot and returns a private token for that participant. The three neutral labels are `A`, `B` and `C`.

If no human slot is available: `409 Conflict`

```json
{
  "detail": "No human slot is available."
}
```

## 2. WebSocket connection

Connect after joining:

```text
ws://<backend-host>/ws?token=<participant_token>
```

Use `wss://` when the application is served over HTTPS. The server resolves the token to the participant and experiment, binds that identity to the connection, and rejects an unknown token during the handshake. The client must not send a sender or voter identity with actions.

The token is an opaque, unguessable association token, not an account or a full authentication system. The backend keeps its token-to-participant mapping in memory for the running experiment. Keep the token private and do not broadcast it or expose it in logs. Participant types and configuration remain server-side and are never included in participant-facing payloads. AI messages use the same event format as human messages.

## 3. Client-to-server events

### `message`

Send during a discussion. The server derives the sender from the connection.

```json
{
  "type": "message",
  "round": 1,
  "text": "I think Player B would be a good decision maker."
}
```

### `vote`

Send once during each voting phase. The candidate must be one of `A`, `B` or `C`; self-voting is allowed.

```json
{
  "type": "vote",
  "candidate": "B"
}
```

The server derives the voter from the connection and the round from the experiment's current state. It validates the voting phase, candidate, and duplicate votes for that voter and round. A rejected action produces an `error` event.

Events containing claimed sender or voter identities are rejected; other
unknown fields are ignored. Configure reverse proxies not to log WebSocket
query strings.

## 4. Server-to-client events

### `state`

Sent individually to the connecting participant and to each connected participant on each phase transition. Each participant receives their own `has_voted` value, not another player's voting status. It drives the four screens: `waiting`, `discussion`, `voting`, and `completed` (results). On a successful vote, send an updated state to that voter; if the vote immediately advances the phase, the next state serves as confirmation.

```json
{
  "type": "state",
  "phase": "discussion",
  "round": 1,
  "players": ["A", "B", "C"],
  "discussion_ends_at": "2026-11-20T21:05:00Z",
  "has_voted": false,
  "messages": [
    {
      "round": 1,
      "sender": "B",
      "text": "Let's discuss who should be the decision maker."
    }
  ]
}
```

- `players` contains the three neutral labels, not participant types or occupancy information.
- `round` is null while waiting, `1` or `2` during the experiment, and `2` when completed.
- `discussion_ends_at` is an ISO 8601 UTC timestamp during discussion and null otherwise; the server controls transitions.
- `has_voted` is `true` only when the receiving participant has voted in the current voting round; it is `false` before they vote and outside voting phases. It resets to `false` for the next round.
- `messages` contains the discussion history so a participant connecting after the phase starts does not miss earlier messages; it is empty before any messages are sent.
- The server sends a consistent snapshot before subsequent live events on each connection. The client replaces its displayed history with the snapshot and appends later `message` events.

For example, during round-one voting, a participant who has voted receives:

```json
{
  "type": "state",
  "phase": "voting",
  "round": 1,
  "players": ["A", "B", "C"],
  "discussion_ends_at": null,
  "has_voted": true,
  "messages": []
}
```

In the same phase, a participant who has not voted receives their own state with `has_voted: false`.

### `message`

Broadcast to all connected participants when a message is accepted. The same shape is used for human and AI senders.

```json
{
  "type": "message",
  "round": 1,
  "sender": "A",
  "text": "I think Player B would be a good decision maker."
}
```

### `result`

Broadcast when round-two voting completes, and sent after `state` if a participant connects after completion. Counts are for round two; ties are resolved by player order A, then B, then C.

```json
{
  "type": "result",
  "round": 2,
  "vote_counts": {
    "A": 1,
    "B": 1,
    "C": 1
  },
  "decision_maker": "A"
}
```

### `error`

Sent only to the client whose action was rejected; for example:

```json
{
  "type": "error",
  "message": "You have already voted in this round."
}
```

## 5. Lifecycle

`waiting → discussion (1) → voting (1) → discussion (2) → voting (2) → completed`

Each discussion lasts approximately one minute. Each voting phase waits for all three votes, including automatic AI votes. Round-one results remain hidden; round-two votes determine the final result. Reconnection and voting timeouts are outside the prototype scope.
