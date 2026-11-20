import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Base, Experiment, Message, Participant, Vote


def make_participants(session: Session) -> tuple[Experiment, Participant, Participant]:
    experiment = Experiment(phase="waiting")
    session.add(experiment)
    session.flush()
    first = Participant(experiment_id=experiment.id, player_label="A", participant_type="human")
    second = Participant(experiment_id=experiment.id, player_label="B", participant_type="ai")
    session.add_all([first, second])
    session.flush()
    return experiment, first, second


def test_persists_entities_and_timestamp(session: Session) -> None:
    """Verify experiment data persists with a timezone-aware message timestamp."""
    experiment, first, second = make_participants(session)
    message = Message(experiment_id=experiment.id, sender_id=first.id, round=1, text="Hello")
    session.add_all(
        [message, Vote(experiment_id=experiment.id, voter_id=first.id, candidate_id=second.id, round=1)]
    )
    experiment.final_decision_maker_id = second.id
    session.flush()
    session.expire_all()

    assert session.get(Experiment, experiment.id).final_decision_maker_id == second.id
    assert session.scalar(select(Message)).created_at.utcoffset() is not None
    assert session.scalar(select(Vote)).candidate_id == second.id


def test_participant_label_is_unique_per_experiment(session: Session) -> None:
    """Verify an experiment cannot contain duplicate participant labels."""
    experiment, _, _ = make_participants(session)
    session.add(Participant(experiment_id=experiment.id, player_label="A", participant_type="ai"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_vote_is_unique_per_voter_and_round(session: Session) -> None:
    """Verify a participant cannot vote twice in the same round."""
    experiment, first, second = make_participants(session)
    session.add_all(
        [
            Vote(experiment_id=experiment.id, voter_id=first.id, candidate_id=second.id, round=1),
            Vote(experiment_id=experiment.id, voter_id=first.id, candidate_id=first.id, round=1),
        ]
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_same_voter_can_vote_in_both_rounds(session: Session) -> None:
    """Verify a participant can vote once in each of the two rounds."""
    experiment, first, second = make_participants(session)
    session.add_all(
        [
            Vote(experiment_id=experiment.id, voter_id=first.id, candidate_id=second.id, round=1),
            Vote(experiment_id=experiment.id, voter_id=first.id, candidate_id=first.id, round=2),
        ]
    )
    session.flush()


@pytest.mark.parametrize("model", [Message, Vote])
def test_rejects_invalid_message_and_vote_rounds(session: Session, model: type[Message] | type[Vote]) -> None:
    """Verify messages and votes reject rounds outside the two-round experiment."""
    experiment, first, second = make_participants(session)
    if model is Message:
        record = Message(experiment_id=experiment.id, sender_id=first.id, round=3, text="Hello")
    else:
        record = Vote(experiment_id=experiment.id, voter_id=first.id, candidate_id=second.id, round=3)
    session.add(record)
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize(
    "invalid",
    [
        Experiment(phase="invalid"),
        Experiment(phase="discussion", current_round=3),
        Participant(experiment_id=1, player_label="D", participant_type="human"),
        Participant(experiment_id=1, player_label="A", participant_type="bot"),
    ],
)
def test_rejects_invalid_values(session: Session, invalid: Base) -> None:
    """Verify invalid experiment phases, rounds, labels and participant types fail."""
    session.add(Experiment(id=1, phase="waiting"))
    session.flush()
    session.add(invalid)
    with pytest.raises(IntegrityError):
        session.flush()


def test_rejects_missing_foreign_key(session: Session) -> None:
    """Verify a participant cannot reference a nonexistent experiment."""
    session.add(Participant(experiment_id=999, player_label="A", participant_type="human"))
    with pytest.raises(IntegrityError):
        session.flush()
