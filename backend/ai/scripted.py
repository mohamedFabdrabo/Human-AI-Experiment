from collections.abc import Sequence

from models import Participant, Vote


def scripted_messages(participants: Sequence[Participant], round_number: int) -> list[tuple[Participant, str]]:
    messages = {
        "A": ("I think Player A could be a good decision maker.", "I still think Player A is a good choice."),
        "B": ("Player A seems like a reasonable choice to me.", "I would choose Player A for the role."),
        "C": ("I suggest considering Player A as decision maker.", "My preference is still Player A."),
    }
    return [
        (participant, messages[participant.player_label][round_number - 1])
        for participant in participants
        if participant.participant_type == "ai"
    ]


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
