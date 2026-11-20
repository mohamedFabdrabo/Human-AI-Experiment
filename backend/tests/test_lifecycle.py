from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import main
from lifecycle import LifecycleError, add_message, advance_discussion, cast_vote, final_results, start_experiment
from models import Experiment, Participant, Vote


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
DURATION = 60


def setup_experiment(session: Session, types: tuple[str, str, str] = ("human", "human", "human")) -> tuple[Experiment, list[Participant]]:
    experiment = Experiment(phase="waiting")
    session.add(experiment)
    session.flush()
    participants = [
        Participant(experiment_id=experiment.id, player_label=label, participant_type=participant_type)
        for label, participant_type in zip("ABC", types)
    ]
    session.add_all(participants)
    session.flush()
    return experiment, participants


def test_full_lifecycle_and_round_two_tie_break(session: Session) -> None:
    experiment, players = setup_experiment(session)
    ids = [player.id for player in players]
    start_experiment(session, experiment.id, set(ids), DURATION, NOW)
    assert (experiment.phase, experiment.current_round, experiment.discussion_ends_at) == (
        "discussion", 1, NOW + timedelta(seconds=60)
    )
    assert not advance_discussion(session, experiment.id, NOW + timedelta(seconds=59))
    assert advance_discussion(session, experiment.id, NOW + timedelta(seconds=60))
    assert (experiment.phase, experiment.current_round, experiment.discussion_ends_at) == ("voting", 1, None)

    for voter in ids[:2]:
        cast_vote(session, experiment.id, voter, ids[2], DURATION, NOW)
        assert experiment.phase == "voting"
    cast_vote(session, experiment.id, ids[2], ids[2], DURATION, NOW + timedelta(seconds=70))
    assert (experiment.phase, experiment.current_round, experiment.discussion_ends_at) == (
        "discussion", 2, NOW + timedelta(seconds=130)
    )
    assert not advance_discussion(session, experiment.id, NOW + timedelta(seconds=129))
    assert advance_discussion(session, experiment.id, NOW + timedelta(seconds=130))
    for voter, candidate in zip(ids, ids):
        cast_vote(session, experiment.id, voter, candidate, DURATION, NOW)
    assert (experiment.phase, experiment.current_round, experiment.final_decision_maker_id) == (
        "completed", 2, ids[0]
    )
    assert final_results(session, experiment.id) == ({"A": 1, "B": 1, "C": 1}, "A")
    assert not advance_discussion(session, experiment.id, NOW + timedelta(days=1))
    with pytest.raises(LifecycleError, match="only accepted"):
        cast_vote(session, experiment.id, ids[0], ids[0], DURATION, NOW)
    with pytest.raises(LifecycleError, match="not waiting"):
        start_experiment(session, experiment.id, set(ids), DURATION, NOW)
    session.expire_all()
    assert final_results(session, experiment.id) == ({"A": 1, "B": 1, "C": 1}, "A")


@pytest.mark.parametrize("types", [("human", "human", "ai"), ("ai", "human", "ai")])
def test_ai_votes_and_humans_are_required_each_round(session: Session, types: tuple[str, str, str]) -> None:
    experiment, players = setup_experiment(session, types)
    humans = [player for player in players if player.participant_type == "human"]
    start_experiment(session, experiment.id, {player.id for player in humans}, DURATION, NOW)
    for round_number in (1, 2):
        assert advance_discussion(session, experiment.id, NOW + timedelta(seconds=round_number * 60))
        votes = session.scalars(select(Vote).where(Vote.experiment_id == experiment.id, Vote.round == round_number)).all()
        assert len(votes) == 3 - len(humans)
        assert all(vote.candidate_id == players[0].id for vote in votes)
        for human in humans:
            assert experiment.phase == "voting"
            cast_vote(session, experiment.id, human.id, players[1].id, DURATION, NOW + timedelta(seconds=60))
    assert experiment.phase == "completed"
    counts, winner = final_results(session, experiment.id)
    assert sum(counts.values()) == 3
    assert winner == ("B" if len(humans) == 2 else "A")


def test_rejects_invalid_actions_and_foreign_participants(session: Session) -> None:
    experiment, players = setup_experiment(session)
    other, outsiders = setup_experiment(session)
    ids = {player.id for player in players}
    with pytest.raises(LifecycleError, match="All human"):
        start_experiment(session, experiment.id, {players[0].id}, DURATION, NOW)
    with pytest.raises(LifecycleError, match="All human"):
        start_experiment(session, experiment.id, ids | {outsiders[0].id}, DURATION, NOW)
    with pytest.raises(LifecycleError, match="only accepted"):
        cast_vote(session, experiment.id, players[0].id, players[0].id, DURATION, NOW)
    with pytest.raises(LifecycleError, match="not available"):
        final_results(session, experiment.id)
    start_experiment(session, experiment.id, ids, DURATION, NOW)
    with pytest.raises(LifecycleError, match="not waiting"):
        start_experiment(session, experiment.id, ids, DURATION, NOW)
    with pytest.raises(LifecycleError, match="only accepted"):
        cast_vote(session, experiment.id, players[0].id, players[0].id, DURATION, NOW)
    assert advance_discussion(session, experiment.id, NOW + timedelta(seconds=60))
    for voter, candidate in [(outsiders[0].id, players[0].id), (players[0].id, outsiders[0].id)]:
        with pytest.raises(LifecycleError, match="belong"):
            cast_vote(session, experiment.id, voter, candidate, DURATION, NOW)
    cast_vote(session, experiment.id, players[0].id, players[0].id, DURATION, NOW)
    with pytest.raises(LifecycleError, match="already voted"):
        cast_vote(session, experiment.id, players[0].id, players[1].id, DURATION, NOW)
    assert session.scalar(select(Experiment).where(Experiment.id == other.id)).phase == "waiting"


def test_invalid_state_and_duration_do_not_advance(session: Session) -> None:
    experiment, players = setup_experiment(session)
    ids = {player.id for player in players}
    with pytest.raises(LifecycleError, match="positive duration"):
        start_experiment(session, experiment.id, ids, 0, NOW)
    assert experiment.phase == "waiting"
    experiment.phase = "voting"
    with pytest.raises(LifecycleError, match="invalid phase or round"):
        advance_discussion(session, experiment.id, NOW)
    experiment.current_round = 1
    cast_vote(session, experiment.id, players[0].id, players[0].id, DURATION, NOW)
    cast_vote(session, experiment.id, players[1].id, players[0].id, DURATION, NOW)
    with pytest.raises(LifecycleError, match="positive duration"):
        cast_vote(session, experiment.id, players[2].id, players[0].id, 0, NOW)
    assert experiment.phase == "voting"
    assert len(session.scalars(select(Vote)).all()) == 2


def test_messages_require_current_discussion_and_participant(session: Session) -> None:
    experiment, players = setup_experiment(session)
    _, outsiders = setup_experiment(session)
    ids = {player.id for player in players}
    with pytest.raises(LifecycleError, match="current discussion"):
        add_message(session, experiment.id, players[0].id, 1, "hello", NOW)
    start_experiment(session, experiment.id, ids, DURATION, NOW)
    with pytest.raises(LifecycleError, match="current discussion"):
        add_message(session, experiment.id, players[0].id, 2, "hello", NOW)
    with pytest.raises(LifecycleError, match="belong"):
        add_message(session, experiment.id, outsiders[0].id, 1, "hello", NOW)
    with pytest.raises(LifecycleError, match="ended"):
        add_message(session, experiment.id, players[0].id, 1, "hello", NOW + timedelta(seconds=60))
    assert add_message(session, experiment.id, players[0].id, 1, "hello", NOW).text == "hello"


def test_last_join_starts_discussion(startup: Path, session: Session) -> None:
    startup.write_text(
        "participants: [human, ai, human]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        assert client.post("/join", json={}).status_code == 201
        session.expire_all()
        experiment = session.get(Experiment, main.app.state.experiment_id)
        assert experiment.phase == "waiting"
        assert client.post("/join", json={}).status_code == 201
        session.expire_all()
        assert (experiment.phase, experiment.current_round) == ("discussion", 1)
        assert experiment.discussion_ends_at is not None


def test_running_server_advances_expired_discussion(startup: Path, session: Session) -> None:
    startup.write_text(
        "participants: [human, ai, ai]\nrounds: 2\ndiscussion_duration_seconds: 1\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        assert client.post("/join", json={}).status_code == 201
        sleep(3)
        session.expire_all()
        experiment = session.get(Experiment, main.app.state.experiment_id)
        assert (experiment.phase, experiment.current_round) == ("voting", 1)
        assert len(session.scalars(select(Vote).where(Vote.experiment_id == experiment.id)).all()) == 2
