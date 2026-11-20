import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from config import load_config
from database import database_url
from models import Base, Experiment, Participant


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.config = load_config(Path(__file__).resolve().parent.parent / "config.yml")
    engine = create_engine(database_url())
    try:
        Base.metadata.create_all(engine)
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
        app.state.join_lock = Lock()
        yield
    finally:
        engine.dispose()


app = FastAPI(lifespan=lifespan)


class JoinResponse(BaseModel):
    player: str
    participant_token: str


@app.post("/join", status_code=status.HTTP_201_CREATED, response_model=JoinResponse)
def join(request: Request, response: Response) -> JoinResponse:
    state = request.app.state
    with state.join_lock:
        with state.session_factory() as session:
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

        token = secrets.token_urlsafe(32)
        while token in state.participant_tokens:
            token = secrets.token_urlsafe(32)
        state.participant_tokens[token] = participant_id
        response.headers["Cache-Control"] = "no-store"
        return JoinResponse(player=player, participant_token=token)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
