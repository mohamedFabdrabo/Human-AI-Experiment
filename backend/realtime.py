import asyncio
import json
import logging
from datetime import timezone
from typing import Literal
from urllib.parse import parse_qs

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from lifecycle import LifecycleError, add_message, advance_discussion, cast_vote, final_results
from models import Experiment, Message, Participant, Vote


logger = logging.getLogger(__name__)


class HideWebSocketQuery:
    """Keep association tokens out of Uvicorn's handshake log."""

    def __init__(self, app: ASGIApp) -> None:
        """Store the application wrapped by this middleware."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Extract the token and hide the WebSocket query from handshake logs."""
        if scope["type"] == "websocket":
            query = parse_qs(
                scope.get("query_string", b"").decode("ascii", errors="replace"),
                keep_blank_values=True,
            )
            tokens = query.get("token", [])
            scope["experiment_token"] = tokens[0] if len(tokens) == 1 else None
            scope["query_string"] = b""
        await self.app(scope, receive, send)


class MessageAction(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    type: Literal["message"]
    round: int = Field(ge=1, le=2)
    text: str


class VoteAction(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    type: Literal["vote"]
    candidate: Literal["A", "B", "C"]


class ExperimentHub:
    def __init__(
        self, session_factory: sessionmaker[Session], experiment_id: int,
        tokens: dict[str, int], discussion_duration: int,
    ) -> None:
        """Set up the experiment's connections and shared state lock."""
        self.session_factory = session_factory
        self.experiment_id = experiment_id
        self.tokens = tokens
        self.discussion_duration = discussion_duration
        self.lock = asyncio.Lock()
        self.connections: dict[WebSocket, int] = {}

    async def _send(self, socket: WebSocket, event: dict) -> None:
        """Send an event and remove a connection if delivery fails."""
        try:
            await socket.send_json(event)
        except (RuntimeError, OSError, WebSocketDisconnect):
            logger.warning("Failed to send a WebSocket update; removing the connection")
            self.connections.pop(socket, None)
            try:
                await socket.close(code=1011)
            except (RuntimeError, OSError, WebSocketDisconnect):
                logger.debug("WebSocket was already closed after delivery failed")

    def _state_events(
        self, session: Session, participant_ids: set[int]
    ) -> tuple[dict[int, dict], dict | None]:
        """Build private state snapshots and an optional final result."""
        experiment = session.get(Experiment, self.experiment_id)
        if experiment is None:
            raise LifecycleError("Experiment does not exist.")
        messages = [
            {"round": message.round, "sender": label, "text": message.text}
            for message, label in session.execute(
                select(Message, Participant.player_label)
                .join(Participant, Message.sender_id == Participant.id)
                .where(Message.experiment_id == self.experiment_id)
                .order_by(Message.id)
            )
        ]
        voted = set()
        if experiment.phase == "voting":
            voted = set(session.scalars(
                select(Vote.voter_id).where(
                    Vote.experiment_id == self.experiment_id,
                    Vote.round == experiment.current_round,
                )
            ))
        deadline = experiment.discussion_ends_at
        state = {
            "type": "state",
            "phase": experiment.phase,
            "round": experiment.current_round,
            "players": ["A", "B", "C"],
            "discussion_ends_at": (
                deadline.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                if deadline is not None else None
            ),
            "messages": messages,
        }
        states = {
            participant_id: {**state, "has_voted": participant_id in voted}
            for participant_id in participant_ids
        }
        result = None
        if experiment.phase == "completed":
            counts, winner = final_results(session, self.experiment_id)
            result = {
                "type": "result", "round": 2, "vote_counts": counts, "decision_maker": winner
            }
        return states, result

    def prepare_states(
        self, session: Session, participant_id: int | None = None
    ) -> list[tuple[WebSocket, dict, dict | None]]:
        """Prepare snapshots for all connections or one participant."""
        recipients = [
            (socket, player_id) for socket, player_id in self.connections.items()
            if participant_id is None or player_id == participant_id
        ]
        if not recipients:
            return []
        states, result = self._state_events(
            session, {player_id for _, player_id in recipients}
        )
        return [(socket, states[player_id], result) for socket, player_id in recipients]

    async def publish_states(self, prepared: list[tuple[WebSocket, dict, dict | None]]) -> None:
        """Send prepared state snapshots and any final result."""
        for socket, state, result in prepared:
            await self._send(socket, state)
            if result is not None and socket in self.connections:
                await self._send(socket, result)

    async def publish_message(self, event: dict) -> None:
        """Send a discussion message to all connected participants."""
        for socket in list(self.connections):
            await self._send(socket, event)

    async def _advance_due(self) -> None:
        """Advance an expired discussion and publish the resulting state."""
        with self.session_factory.begin() as session:
            advanced = advance_discussion(session, self.experiment_id)
            prepared = self.prepare_states(session) if advanced else []
        if advanced:
            await self.publish_states(prepared)

    async def tick(self) -> None:
        """Check the discussion deadline while holding the state lock."""
        async with self.lock:
            await self._advance_due()

    async def connect(self, socket: WebSocket) -> None:
        """Authenticate a socket, send its snapshot and handle its events."""
        token = socket.scope.get("experiment_token")
        async with self.lock:
            participant_id = self.tokens.get(token) if isinstance(token, str) else None
            if participant_id is None:
                await socket.close(code=1008)
                return
            await self._advance_due()
            with self.session_factory() as session:
                states, result = self._state_events(session, {participant_id})
            await socket.accept()
            self.connections[socket] = participant_id
            await self._send(socket, states[participant_id])
            if result is not None and socket in self.connections:
                await self._send(socket, result)
            if socket not in self.connections:
                return
        try:
            while True:
                frame = await socket.receive()
                if frame["type"] == "websocket.disconnect":
                    break
                text = frame.get("text")
                binary = frame.get("bytes")
                if text is None and binary is not None:
                    try:
                        text = binary.decode("utf-8")
                    except UnicodeDecodeError:
                        pass
                if text is None:
                    async with self.lock:
                        await self._send(socket, {"type": "error", "message": "Invalid event."})
                else:
                    await self._handle(socket, participant_id, text)
        except WebSocketDisconnect:
            pass
        finally:
            async with self.lock:
                self.connections.pop(socket, None)

    async def _handle(self, socket: WebSocket, participant_id: int, text: str) -> None:
        """Validate an action, apply it transactionally and publish updates."""
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("Event must be an object.")
            if any(
                field in data for field in
                ("sender", "sender_id", "voter", "voter_id", "participant", "participant_id", "player")
            ):
                raise ValueError("Events cannot claim a sender or voter identity.")
            if data.get("type") == "message":
                action = MessageAction.model_validate(data)
            elif data.get("type") == "vote":
                action = VoteAction.model_validate(data)
            else:
                raise ValueError("Unknown event type.")
        except (ValueError, ValidationError):
            async with self.lock:
                await self._send(socket, {"type": "error", "message": "Invalid event."})
            return

        async with self.lock:
            if socket not in self.connections:
                return
            try:
                await self._advance_due()
                with self.session_factory.begin() as session:
                    if isinstance(action, MessageAction):
                        message = add_message(
                            session, self.experiment_id, participant_id,
                            action.round, action.text,
                        )
                        sender = session.get(Participant, participant_id)
                        if sender is None:
                            raise LifecycleError("Sender does not exist.")
                        event = {
                            "type": "message", "round": message.round,
                            "sender": sender.player_label, "text": message.text,
                        }
                    else:
                        candidate = session.scalar(
                            select(Participant).where(
                                Participant.experiment_id == self.experiment_id,
                                Participant.player_label == action.candidate,
                            )
                        )
                        if candidate is None:
                            raise LifecycleError("Candidate does not belong to the experiment.")
                        cast_vote(
                            session, self.experiment_id, participant_id, candidate.id,
                            self.discussion_duration,
                        )
                        experiment = session.get(Experiment, self.experiment_id)
                        if experiment is None:
                            raise LifecycleError("Experiment does not exist.")
                        phase_changed = experiment.phase != "voting"
                        prepared = self.prepare_states(
                            session, None if phase_changed else participant_id
                        )
                if isinstance(action, MessageAction):
                    await self.publish_message(event)
                else:
                    await self.publish_states(prepared)
            except LifecycleError as exc:
                await self._send(socket, {"type": "error", "message": str(exc)})
            except SQLAlchemyError:
                logger.exception("Failed to process an experiment action")
                await self._send(socket, {"type": "error", "message": "Unable to process the event."})
