# Implementation Blueprint

This blueprint follows the [original assessment](./technical-assessment-multi-participant-human-ai-experiment-platform-v4.md). **Required** means specified by the assessment; **assumption** means a simple implementation choice, not an assessment requirement.

## 1. Four UI screens

1. **Waiting room:** Join the experiment and wait until all required human participants have joined. Show neutral player identifiers without revealing participant types.
2. **Discussion:** Show the current round, the shared text conversation, a message input and the remaining discussion time. Human and AI messages use the same presentation.
3. **Voting:** Let the human select one of the three players and submit one vote. Wait for all participants to vote.
4. **Results:** Show the final vote counts and selected Decision Maker using neutral identifiers.

## 2. Backend responsibilities

- Read `config.yml` from the repository root and support the three required configurations: 3 humans, 2 humans + 1 AI, and 1 human + 2 AI.
- Assign exactly three distinct neutral player identifiers and start when all required humans have joined.
- Run two approximately one-minute discussion rounds, followed by a vote from each participant in each round.
- Relay discussion messages and phase changes in real time; enforce phase and voting rules on the server.
- Generate AI discussion messages and votes, count votes, select the Decision Maker and broadcast the final result.
- Store experiment data in the database. Do not send human/AI types or configuration to participants.

**Assumptions:** Run one experiment at a time. Use simple scripted AI messages and votes; no external AI service is necessary. A participant may vote for themselves. Round-one results are not displayed, and round-two votes determine the final result. Break ties by neutral player order (A, then B, then C). Voting waits for all three votes; disconnection recovery and voting timeouts are outside this prototype.

## 3. Minimum database entities

The assessment requires MongoDB or PostgreSQL. The following are logical entities; they do not prescribe a particular schema.

- **Experiment:** configuration, current phase and round, and final Decision Maker.
- **Participant:** experiment, neutral identifier and human/AI type.
- **Message:** experiment, round, participant and text.
- **Vote:** experiment, round, voter and selected participant; at most one vote per participant per round.

The participant type is server-side data, not participant-visible data.

## 4. Experiment lifecycle

`Waiting room → Discussion 1 → Voting 1 → Discussion 2 → Voting 2 → Results`

The server begins discussion when the configured human slots are filled and AI slots are assigned. Each discussion ends after approximately one minute. Each voting phase ends when all three votes are received; after the second voting phase, the server calculates and sends the final result.

## 5. Essential REST endpoints and WebSocket events

**Assumption:** The following is one minimal interface, not a prescribed assessment API. A join returns an opaque participant token, used to associate subsequent actions with that participant; it is not an authentication system.

| Interface | Purpose |
|---|---|
| `POST /join` | Assign an available human slot and return its neutral identifier and token, or report that the session is full. |
| `WebSocket /ws` | Connect using the participant token for real-time updates and actions. |

| WebSocket event | Direction | Purpose |
|---|---|---|
| `state` | Server → client | Send each participant their own state, including phase, round, timing and personal voting status, on connection and transition. |
| `message` | Client → server → clients | Submit and broadcast a discussion message with its neutral sender. |
| `vote` | Client → server | Submit one candidate selection for the current voting round. |
| `result` | Server → clients | Deliver final vote counts and the selected Decision Maker. |
| `error` | Server → client | Report an invalid action. |

AI actions occur on the server and use the same participant-visible message and result formats as human actions.

## 6. Minimum Docker services

- **Frontend:** React application.
- **Backend:** Python/FastAPI application.
- **Database:** PostgreSQL or MongoDB.

Docker Compose starts the complete application locally with one command. The repository must include `config.yml` at its root, Docker setup, a concise README covering startup, configuration and key choices, and an AI usage log as specified in the assessment.
