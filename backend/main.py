import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from config import load_config
from database import database_url, initialize_schema
from lifecycle import start_experiment
from models import Experiment, Participant
from realtime import ExperimentHub, HideWebSocketQuery


logger = logging.getLogger(__name__)


async def run_lifecycle(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(1)
        try:
            await app.state.hub.tick()
        except Exception:
            logger.exception("Failed to advance experiment lifecycle")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.config = load_config(Path(__file__).resolve().parent.parent / "config.yml")
    engine = create_engine(database_url())
    try:
        with engine.begin() as connection:
            initialize_schema(connection)
        app.state.session_factory = sessionmaker(bind=engine)
        with app.state.session_factory.begin() as session:
            experiment = Experiment(phase="waiting")
            session.add(experiment)
            session.flush()
            experiment_id = experiment.id
            session.add_all(
                [
                    Participant(
                        experiment_id=experiment_id,
                        player_label=label,
                        participant_type=participant_type,
                    )
                    for label, participant_type in zip("ABC", app.state.config.participants)
                ]
            )
        app.state.experiment_id = experiment_id
        app.state.participant_tokens = {}
        app.state.hub = ExperimentHub(
            app.state.session_factory, experiment_id, app.state.participant_tokens,
            app.state.config.discussion_duration_seconds,
        )
        lifecycle_task = asyncio.create_task(run_lifecycle(app))
        try:
            yield
        finally:
            lifecycle_task.cancel()
            try:
                await lifecycle_task
            except asyncio.CancelledError:
                pass
    finally:
        engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)
app.add_middleware(HideWebSocketQuery)


class JoinResponse(BaseModel):
    player: str
    participant_token: str


@app.post("/join", status_code=status.HTTP_201_CREATED, response_model=JoinResponse)
async def join(request: Request, response: Response) -> JoinResponse:
    state = request.app.state
    async with state.hub.lock:
        token = secrets.token_urlsafe(32)
        while token in state.participant_tokens:
            token = secrets.token_urlsafe(32)
        prepared = []
        ai_messages = []
        with state.session_factory.begin() as session:
            participants = session.scalars(
                select(Participant)
                .where(
                    Participant.experiment_id == state.experiment_id,
                    Participant.participant_type == "human",
                )
                .order_by(Participant.player_label)
            ).all()
            occupied = set(state.participant_tokens.values())
            participant = next((p for p in participants if p.id not in occupied), None)
            if participant is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No human slot is available.",
                )
            player, participant_id = participant.player_label, participant.id
            joined_humans = occupied | {participant_id}
            if len(joined_humans) == len(participants):
                transition_time = datetime.now(timezone.utc)
                start_experiment(
                    session, state.experiment_id, joined_humans,
                    state.config.discussion_duration_seconds, transition_time,
                )
                prepared = state.hub.prepare_states(session)
                ai_messages = state.hub.prepare_ai_messages(session, 1, transition_time)
        state.participant_tokens[token] = participant_id
        await state.hub.publish_states(prepared)
        for ai_message in ai_messages:
            await state.hub.publish_message(ai_message)
        response.headers["Cache-Control"] = "no-store"
        return JoinResponse(player=player, participant_token=token)


@app.websocket("/ws")
async def websocket_endpoint(socket: WebSocket) -> None:
    await socket.app.state.hub.connect(socket)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
