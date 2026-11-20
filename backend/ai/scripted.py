from collections.abc import Sequence

from models import Participant, Vote


def scripted_votes(participants: Sequence[Participant], round_number: int) -> list[Vote]:
    """Create the existing scripted vote for each AI participant."""
    return [
        Vote(
            experiment_id=participant.experiment_id,
            voter_id=participant.id,
            candidate_id=participants[0].id,
            round=round_number,
        )
        for participant in participants
        if participant.participant_type == "ai"
    ]
