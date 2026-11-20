from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai.scripted import scripted_votes
from models import Experiment, Message, Participant, Vote


class LifecycleError(ValueError):
    """An action is incompatible with the experiment's current state."""


def _experiment(session: Session, experiment_id: int) -> Experiment:
    experiment = session.scalar(
        select(Experiment)
        .where(Experiment.id == experiment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if experiment is None:
        raise LifecycleError("Experiment does not exist.")
    valid = (
        (experiment.phase == "waiting" and experiment.current_round is None)
        or (experiment.phase in ("discussion", "voting") and experiment.current_round in (1, 2))
        or (experiment.phase == "completed" and experiment.current_round == 2)
    )
    if not valid:
        raise LifecycleError("Experiment has an invalid phase or round.")
    if (experiment.phase == "discussion") != (experiment.discussion_ends_at is not None):
        raise LifecycleError("Experiment has an invalid discussion deadline.")
    if (experiment.phase == "completed") != (experiment.final_decision_maker_id is not None):
        raise LifecycleError("Experiment has an invalid final decision maker.")
    return experiment


def _participants(session: Session, experiment_id: int) -> list[Participant]:
    participants = list(
        session.scalars(
            select(Participant)
            .where(Participant.experiment_id == experiment_id)
            .order_by(Participant.player_label)
        )
    )
    if [participant.player_label for participant in participants] != ["A", "B", "C"]:
        raise LifecycleError("Experiment must have three participant slots.")
    return participants


def _start_discussion(experiment: Experiment, round_number: int, duration: int, now: datetime) -> None:
    if duration <= 0 or now.utcoffset() is None:
        raise LifecycleError("Discussion requires a positive duration and timezone-aware time.")
    experiment.phase = "discussion"
    experiment.current_round = round_number
    experiment.discussion_ends_at = now + timedelta(seconds=duration)


def start_experiment(
    session: Session,
    experiment_id: int,
    joined_human_ids: set[int],
    duration: int,
    now: datetime | None = None,
) -> None:
    experiment = _experiment(session, experiment_id)
    if experiment.phase != "waiting":
        raise LifecycleError("Experiment is not waiting.")
    participants = _participants(session, experiment_id)
    human_ids = {participant.id for participant in participants if participant.participant_type == "human"}
    if not human_ids or joined_human_ids != human_ids:
        raise LifecycleError("All human participants must join before starting.")
    _start_discussion(experiment, 1, duration, now or datetime.now(timezone.utc))


def advance_discussion(
    session: Session, experiment_id: int, now: datetime | None = None
) -> bool:
    """End a discussion if its deadline has passed; return whether it advanced."""
    experiment = _experiment(session, experiment_id)
    if experiment.phase != "discussion":
        return False
    current_time = now or datetime.now(timezone.utc)
    if current_time.utcoffset() is None:
        raise LifecycleError("Current time must be timezone-aware.")
    deadline = experiment.discussion_ends_at
    if deadline is None:
        raise LifecycleError("Discussion has no deadline.")
    if current_time < deadline:
        return False
    round_number = experiment.current_round
    if round_number not in (1, 2):
        raise LifecycleError("Discussion has an invalid round.")
    participants = _participants(session, experiment_id)
    experiment.phase = "voting"
    experiment.discussion_ends_at = None
    session.add_all(scripted_votes(participants, round_number))
    session.flush()
    return True


def cast_vote(
    session: Session,
    experiment_id: int,
    voter_id: int,
    candidate_id: int,
    duration: int,
    now: datetime | None = None,
) -> None:
    experiment = _experiment(session, experiment_id)
    if experiment.phase != "voting" or experiment.current_round not in (1, 2):
        raise LifecycleError("Votes are only accepted during voting.")
    participants = _participants(session, experiment_id)
    participant_ids = {participant.id for participant in participants}
    if voter_id not in participant_ids or candidate_id not in participant_ids:
        raise LifecycleError("Voter and candidate must belong to the experiment.")
    votes = list(
        session.scalars(
            select(Vote).where(
                Vote.experiment_id == experiment_id, Vote.round == experiment.current_round
            )
        )
    )
    if any(vote.voter_id not in participant_ids or vote.candidate_id not in participant_ids for vote in votes):
        raise LifecycleError("Experiment contains an invalid vote.")
    if any(vote.voter_id == voter_id for vote in votes):
        raise LifecycleError("Participant has already voted in this round.")
    if len(votes) >= len(participants):
        raise LifecycleError("Voting has already received all votes.")
    round_number = experiment.current_round
    if len(votes) == len(participants) - 1 and round_number == 1:
        _start_discussion(experiment, 2, duration, now or datetime.now(timezone.utc))
    vote = Vote(
        experiment_id=experiment_id,
        voter_id=voter_id,
        candidate_id=candidate_id,
        round=round_number,
    )
    session.add(vote)
    votes.append(vote)
    if len(votes) == len(participants):
        if round_number == 2:
            counts = Counter(existing_vote.candidate_id for existing_vote in votes)
            experiment.final_decision_maker_id = max(
                participants, key=lambda participant: counts[participant.id]
            ).id
            experiment.phase = "completed"
    session.flush()


def add_message(
    session: Session,
    experiment_id: int,
    sender_id: int,
    round_number: int,
    text: str,
    now: datetime | None = None,
) -> Message:
    experiment = _experiment(session, experiment_id)
    if experiment.phase != "discussion" or experiment.current_round != round_number:
        raise LifecycleError("Messages are only accepted in the current discussion round.")
    current_time = now or datetime.now(timezone.utc)
    if current_time.utcoffset() is None:
        raise LifecycleError("Current time must be timezone-aware.")
    if experiment.discussion_ends_at is None or current_time >= experiment.discussion_ends_at:
        raise LifecycleError("Discussion has ended.")
    if sender_id not in {participant.id for participant in _participants(session, experiment_id)}:
        raise LifecycleError("Sender must belong to the experiment.")
    message = Message(
        experiment_id=experiment_id, sender_id=sender_id, round=round_number, text=text
    )
    session.add(message)
    session.flush()
    return message


def final_results(session: Session, experiment_id: int) -> tuple[dict[str, int], str]:
    experiment = _experiment(session, experiment_id)
    if experiment.phase != "completed":
        raise LifecycleError("Results are not available before completion.")
    participants = _participants(session, experiment_id)
    votes = list(
        session.scalars(select(Vote).where(Vote.experiment_id == experiment_id, Vote.round == 2))
    )
    participant_ids = {participant.id for participant in participants}
    if (
        {vote.voter_id for vote in votes} != participant_ids
        or len(votes) != len(participants)
        or any(vote.candidate_id not in participant_ids for vote in votes)
        or experiment.final_decision_maker_id not in participant_ids
    ):
        raise LifecycleError("Experiment contains invalid final results.")
    counts = Counter(vote.candidate_id for vote in votes)
    winner = max(participants, key=lambda participant: counts[participant.id])
    if experiment.final_decision_maker_id != winner.id:
        raise LifecycleError("Experiment contains an invalid final decision maker.")
    return {participant.player_label: counts[participant.id] for participant in participants}, winner.player_label
