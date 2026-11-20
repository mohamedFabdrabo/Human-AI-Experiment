# Frontend Design and Architecture

This design follows the [implementation blueprint](./implementation-blueprint.md) and [communication contract](./communication-contract.md). Visual and layout choices below are implementation assumptions.

## Shared design

- **Style:** Light background, dark readable text, restrained borders and blue primary actions. Use neutral language and identical presentation for all participants.
- **Layout:** A centered, readable content area for desktop; on smaller screens, use the available width with comfortable padding and stack controls vertically.
- **Accessibility:** Use clear labels, keyboard-accessible controls, visible focus states and sufficient contrast.
- **Shared components:** App shell and header, primary button, status/error message, and participant label. Reuse these across screens.
- **Privacy:** Show only neutral labels (`Player A`, `Player B`, `Player C`), never participant types, configuration, or human/AI-specific styling.
- **Frontend state:** Keep the participant's label and token, current server state, messages, and final result in application state. Render the screen from the server's phase; the server controls transitions and timing.

## 1. Waiting room

**Layout and hierarchy**

- App shell
  - Header: experiment title and the participant's label once assigned
  - Waiting panel: title, brief waiting status, and join button before joining
  - Status/error message

**Information:** Explain that the experiment begins when the required participants have joined. Do not show participant types or slot occupancy.

**Interaction and states:**

- Select **Join experiment** once to request a slot.
- While joining, disable the button and show a loading status.
- After joining, show a waiting status until the server starts discussion.
- Show an error if joining or connecting fails. When the server announces discussion, switch to the discussion screen.

**Contract:** `POST /join`; connect to `WebSocket /ws` with the returned token; receive `state` and `error`.

## 2. Discussion room

**Layout and hierarchy**

- App shell and header
  - Round number and remaining discussion time
  - Conversation panel: message list with neutral sender labels
  - Message input and blue **Send** button
  - Status/error message

**Information:** Show the current round, the discussion history and a countdown derived from the server's discussion deadline. Present all messages consistently.

**Interaction and states:**

- Enter text and select **Send** during discussion.
- Show a loading status while the initial state is being received.
- Show an error when an action or connection fails.
- When discussion ends, disable message submission and switch to voting on the server's phase update.

**Contract:** Receive `state` and `message`; send `message`; receive `error`. Replace history from a `state` snapshot and append subsequent `message` events.

## 3. Voting screen

**Layout and hierarchy**

- App shell and header
  - Round number and voting prompt
  - Single-choice list: Player A, Player B, Player C
  - Blue **Submit vote** button
  - Status/error message

**Information:** Ask the participant to choose one of the three players as Decision Maker. Self-voting is allowed. Do not display round-one results.

**Interaction and states:**

- Select one candidate and submit once; disable submission while the vote is pending.
- If rejected, display the error and allow correction when appropriate.
- Once the server confirms the vote, disable the choices and show a waiting status.
- On the next server phase update, show round-two discussion or results as applicable.

**Contract:** Receive the participant-specific `state`, including their own boolean `has_voted`; send `vote` with the candidate only; receive `error`. The backend determines the current round.

## 4. Results screen

**Layout and hierarchy**

- App shell and header
  - Results panel: selected Decision Maker
  - Round-two vote counts for Player A, Player B and Player C
  - Status message

**Information:** Show the final Decision Maker and round-two vote counts using neutral labels.

**Interaction and states:**

- Show a loading status if the experiment is complete but the `result` event has not arrived.
- Once received, display the result as read-only.
- Show a connection error if the result cannot be received; no restart or reconnection feature is required.

**Contract:** Receive `state` with phase `completed`, followed by `result`.
