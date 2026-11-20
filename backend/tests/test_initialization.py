import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import DDL, event, select
from sqlalchemy.orm import Session

import main
from database import initialize_schema
from models import Experiment, Participant


def test_existing_schema_gets_discussion_deadline(session: Session) -> None:
    experiment = Experiment(phase="waiting")
    session.add(experiment)
    session.flush()
    connection = session.connection()
    connection.execute(
        DDL("ALTER TABLE %(fullname)s DROP COLUMN discussion_ends_at").against(Experiment.__table__)
    )
    initialize_schema(connection)
    initialize_schema(connection)
    session.refresh(experiment)
    assert experiment.phase == "waiting"
    assert experiment.discussion_ends_at is None


@pytest.mark.parametrize(
    "participants",
    [
        ["human", "human", "human"],
        ["human", "human", "ai"],
        ["ai", "human", "ai"],
    ],
)
def test_startup_creates_configured_experiment(
    startup: Path, session: Session, participants: list[str]
) -> None:
    """Verify startup creates a waiting experiment with the configured slots."""
    startup.write_text(
        f"participants: [{', '.join(participants)}]\n"
        "rounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    app = FastAPI()

    async def start() -> None:
        async with main.lifespan(app):
            experiment = session.get(Experiment, app.state.experiment_id)
            assert experiment is not None
            assert experiment.phase == "waiting"
            assert experiment.current_round is None
            assert experiment.final_decision_maker_id is None
            slots = session.scalars(
                select(Participant)
                .where(Participant.experiment_id == experiment.id)
                .order_by(Participant.player_label)
            ).all()
            assert [(slot.player_label, slot.participant_type) for slot in slots] == list(
                zip("ABC", participants)
            )

    asyncio.run(start())


def test_restart_creates_a_new_experiment(startup: Path, session: Session) -> None:
    """Verify each startup creates a new experiment rather than resuming one."""
    startup.write_text(
        "participants: [human, human, ai]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    app = FastAPI()

    async def start_twice() -> None:
        async with main.lifespan(app):
            first_id = app.state.experiment_id
        async with main.lifespan(app):
            assert app.state.experiment_id != first_id

    asyncio.run(start_twice())
    assert len(session.scalars(select(Experiment)).all()) == 2
    assert len(session.scalars(select(Participant)).all()) == 6


def test_startup_rolls_back_experiment_if_slot_creation_fails(
    startup: Path, session: Session
) -> None:
    """Verify a slot insertion failure rolls back the entire experiment."""
    startup.write_text(
        "participants: [human, human, ai]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )

    def fail_insert(*args: object) -> None:
        raise RuntimeError("slot insertion failed")

    async def start() -> None:
        async with main.lifespan(FastAPI()):
            pytest.fail("startup should have failed")

    event.listen(Participant, "before_insert", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="slot insertion failed"):
            asyncio.run(start())
    finally:
        event.remove(Participant, "before_insert", fail_insert)
    assert session.scalars(select(Experiment)).all() == []
    assert session.scalars(select(Participant)).all() == []
