from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import main
from models import Participant


@pytest.mark.parametrize(
    ("participants", "expected_players"),
    [
        ("human, human, human", ["A", "B", "C"]),
        ("human, ai, human", ["A", "C"]),
        ("ai, human, ai", ["B"]),
    ],
)
def test_join_assigns_only_available_human_slots(
    startup: Path, session: Session, participants: str, expected_players: list[str]
) -> None:
    """Verify joins assign human slots with private tokens and reject excess joins."""
    startup.write_text(
        f"participants: [{participants}]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        tokens = []
        for expected_player in expected_players:
            response = client.post("/join", json={})
            assert response.status_code == 201
            assert response.headers["cache-control"] == "no-store"
            body = response.json()
            assert set(body) == {"player", "participant_token"}
            assert body["player"] == expected_player
            tokens.append(body["participant_token"])
            participant = session.scalar(
                select(Participant).where(
                    Participant.id == main.app.state.participant_tokens[body["participant_token"]]
                )
            )
            assert participant is not None
            assert participant.player_label == expected_player
            assert participant.participant_type == "human"
        assert all(tokens)
        assert len(set(tokens)) == len(tokens)

        response = client.post("/join", json={})
        assert response.status_code == 409
        assert response.json() == {"detail": "No human slot is available."}
        assert client.get("/health").json() == {"status": "ok"}


def test_concurrent_joins_do_not_assign_the_same_slot(startup: Path) -> None:
    """Verify concurrent joins cannot assign a slot or token more than once."""
    startup.write_text(
        "participants: [human, human, human]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(executor.map(lambda _: client.post("/join", json={}), range(8)))
        accepted = [response.json() for response in responses if response.status_code == 201]
        assert sorted(response.status_code for response in responses) == [201] * 3 + [409] * 5
        assert {body["player"] for body in accepted} == {"A", "B", "C"}
        assert len({body["participant_token"] for body in accepted}) == 3
