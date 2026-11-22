import asyncio
import logging
import socket
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import uvicorn
from fastapi import WebSocket
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect

import main
from models import Experiment, Message, Participant, Vote
from realtime import ExperimentHub, HideWebSocketQuery


def expire_discussion(client: TestClient, advance: bool = True) -> None:
    async def expire() -> None:
        hub = main.app.state.hub
        async with hub.lock:
            with hub.session_factory.begin() as session:
                experiment = session.get(Experiment, hub.experiment_id)
                experiment.discussion_ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        if advance:
            await hub.tick()

    client.portal.call(expire)


def assert_state(event: dict, phase: str, round_number: int | None, has_voted: bool = False) -> None:
    assert set(event) == {
        "type", "phase", "round", "players", "discussion_ends_at", "has_voted", "messages"
    }
    assert event["type"] == "state"
    assert (event["phase"], event["round"], event["has_voted"]) == (phase, round_number, has_voted)
    assert event["players"] == ["A", "B", "C"]
    assert (event["discussion_ends_at"] is not None) == (phase == "discussion")


def test_websocket_full_flow_private_state_and_history(startup: Path, session: Session) -> None:
    startup.write_text(
        "participants: [human, human, ai]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        alice_token = client.post("/join", json={}).json()["participant_token"]
        with client.websocket_connect(f"/ws?token={alice_token}") as alice:
            assert_state(alice.receive_json(), "waiting", None)
            alice.send_json({"type": "message", "round": 1, "text": "too early"})
            assert alice.receive_json()["type"] == "error"
            bob_token = client.post("/join", json={}).json()["participant_token"]
            assert_state(alice.receive_json(), "discussion", 1)
            ai_message_1 = alice.receive_json()
            assert ai_message_1["type"] == "message"
            assert (ai_message_1["round"], ai_message_1["sender"]) == (1, "C")
            assert ai_message_1["text"]
            with client.websocket_connect(f"/ws?token={bob_token}") as bob:
                initial = bob.receive_json()
                assert_state(initial, "discussion", 1)
                assert initial["messages"] == [{k: v for k, v in ai_message_1.items() if k != "type"}]
                alice.send_json({"type": "message", "round": 1, "text": "Hello"})
                message = {"type": "message", "round": 1, "sender": "A", "text": "Hello"}
                assert alice.receive_json() == message
                assert bob.receive_json() == message
                bob.send_json({"type": "message", "round": 1, "text": "forged", "sender": "A"})
                assert bob.receive_json()["type"] == "error"
                bob.send_json({"type": "message", "round": 2, "text": "wrong round"})
                assert bob.receive_json()["type"] == "error"
                bob.send_json({"type": "vote", "candidate": "A"})
                assert bob.receive_json()["type"] == "error"

                expire_discussion(client)
                assert_state(alice.receive_json(), "voting", 1)
                assert_state(bob.receive_json(), "voting", 1)
                bob.send_json({"type": "message", "round": 1, "text": "during voting"})
                assert bob.receive_json()["type"] == "error"
                alice.send_json({"type": "vote", "candidate": "B"})
                assert_state(alice.receive_json(), "voting", 1, True)
                with client.websocket_connect(f"/ws?token={bob_token}") as bob_again:
                    assert_state(bob_again.receive_json(), "voting", 1, False)
                bob.send_json({"type": "vote", "candidate": "D"})
                assert bob.receive_json()["type"] == "error"
                alice.send_json({"type": "vote", "candidate": "B"})
                assert alice.receive_json()["type"] == "error"

                with client.websocket_connect(f"/ws?token={alice_token}") as alice_again:
                    snapshot = alice_again.receive_json()
                    assert_state(snapshot, "voting", 1, True)
                    assert snapshot["messages"] == initial["messages"] + [
                        {"round": 1, "sender": "A", "text": "Hello"}
                    ]
                    bob.send_json({"type": "vote", "candidate": "B"})
                    for ws in (alice, bob, alice_again):
                        state = ws.receive_json()
                        assert_state(state, "discussion", 2)
                        assert state["messages"] == snapshot["messages"]
                    ai_message_2 = alice.receive_json()
                    assert ai_message_2["type"] == "message"
                    assert (ai_message_2["round"], ai_message_2["sender"]) == (2, "C")
                    assert ai_message_2["text"]
                    for ws in (bob, alice_again):
                        assert ws.receive_json() == ai_message_2
                    bob.send_json({"type": "message", "round": 1, "text": "old round"})
                    assert bob.receive_json()["type"] == "error"
                    bob.send_json({"type": "message", "round": 2, "text": "Round two"})
                    message = {"type": "message", "round": 2, "sender": "B", "text": "Round two"}
                    for ws in (alice, bob, alice_again):
                        assert ws.receive_json() == message
                    expire_discussion(client)
                    for ws in (alice, bob, alice_again):
                        assert_state(ws.receive_json(), "voting", 2)
                    alice.send_json({"type": "vote", "candidate": "B"})
                    assert_state(alice.receive_json(), "voting", 2, True)
                    assert_state(alice_again.receive_json(), "voting", 2, True)
                    bob.send_json({"type": "vote", "candidate": "C"})
                    result = {
                        "type": "result", "round": 2,
                        "vote_counts": {"A": 1, "B": 1, "C": 1}, "decision_maker": "A",
                    }
                    for ws in (alice, bob, alice_again):
                        assert_state(ws.receive_json(), "completed", 2)
                        assert ws.receive_json() == result
                    alice.send_json({"type": "message", "round": 2, "text": "too late"})
                    assert alice.receive_json()["type"] == "error"
                with client.websocket_connect(f"/ws?token={bob_token}") as reconnected:
                    assert_state(reconnected.receive_json(), "completed", 2)
                    assert reconnected.receive_json() == result
        session.expire_all()
        stored = session.execute(
            select(Message, Participant.player_label)
            .join(Participant, Message.sender_id == Participant.id)
            .order_by(Message.id)
        ).all()
        assert [
            (message.experiment_id, message.round, label, message.text)
            for message, label in stored
        ] == [
            (main.app.state.experiment_id, 1, "C", ai_message_1["text"]),
            (main.app.state.experiment_id, 1, "A", "Hello"),
            (main.app.state.experiment_id, 2, "C", ai_message_2["text"]),
            (main.app.state.experiment_id, 2, "B", "Round two"),
        ]


@pytest.mark.parametrize(
    ("participants", "ai_labels"),
    [("human, ai, ai", ("B", "C")), ("ai, human, ai", ("A", "C"))],
)
def test_two_ai_participants_send_and_vote_in_both_rounds(
    startup: Path, session: Session, participants: str, ai_labels: tuple[str, str]
) -> None:
    startup.write_text(
        f"participants: [{participants}]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        token = client.post("/join", json={}).json()["participant_token"]
        with client.websocket_connect(f"/ws?token={token}") as first:
            initial = first.receive_json()
            assert_state(initial, "discussion", 1)
            assert [(message["round"], message["sender"]) for message in initial["messages"]] == [
                (1, label) for label in ai_labels
            ]
            assert all(message["text"] for message in initial["messages"])
            with client.websocket_connect(f"/ws?token={token}") as second:
                assert second.receive_json()["messages"] == initial["messages"]
                expire_discussion(client)
                for ws in (first, second):
                    assert_state(ws.receive_json(), "voting", 1)
                first.send_json({"type": "vote", "candidate": "B"})
                for ws in (first, second):
                    state = ws.receive_json()
                    assert_state(state, "discussion", 2)
                    assert state["messages"] == initial["messages"]
                round_two = [first.receive_json(), first.receive_json()]
                assert [(event["type"], event["round"], event["sender"]) for event in round_two] == [
                    ("message", 2, label) for label in ai_labels
                ]
                assert [second.receive_json(), second.receive_json()] == round_two
                assert all(event["text"] for event in round_two)
                expire_discussion(client)
                for ws in (first, second):
                    assert_state(ws.receive_json(), "voting", 2)
                first.send_json({"type": "vote", "candidate": "B"})
                for ws in (first, second):
                    assert_state(ws.receive_json(), "completed", 2)
                    assert ws.receive_json() == {
                        "type": "result", "round": 2,
                        "vote_counts": {"A": 2, "B": 1, "C": 0}, "decision_maker": "A",
                    }
        session.expire_all()
        messages = session.execute(
            select(Message, Participant)
            .join(Participant, Message.sender_id == Participant.id)
            .order_by(Message.id)
        ).all()
        assert [(message.round, sender.player_label) for message, sender in messages] == [
            (round_number, label) for round_number in (1, 2) for label in ai_labels
        ]
        assert all(sender.participant_type == "ai" for _, sender in messages)
        votes = session.scalars(select(Vote)).all()
        assert len(votes) == 6
        assert sum(vote.round == 1 for vote in votes) == 3
        assert sum(vote.round == 2 for vote in votes) == 3


def test_three_humans_complete_both_voting_rounds(startup: Path) -> None:
    startup.write_text(
        "participants: [human, human, human]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client, ExitStack() as stack:
        tokens = [client.post("/join", json={}).json()["participant_token"] for _ in range(3)]
        sockets = [stack.enter_context(client.websocket_connect(f"/ws?token={token}")) for token in tokens]
        for ws in sockets:
            state = ws.receive_json()
            assert_state(state, "discussion", 1)
            assert state["messages"] == []
        for round_number in (1, 2):
            expire_discussion(client)
            for ws in sockets:
                assert_state(ws.receive_json(), "voting", round_number)
            for ws, candidate in zip(sockets[:2], ("A", "B")):
                ws.send_json({"type": "vote", "candidate": candidate})
                assert_state(ws.receive_json(), "voting", round_number, True)
            sockets[2].send_json({"type": "vote", "candidate": "C"})
            for ws in sockets:
                state = ws.receive_json()
                assert_state(state, "discussion" if round_number == 1 else "completed", 2)
                assert state["messages"] == []
                if round_number == 2:
                    assert ws.receive_json() == {
                        "type": "result", "round": 2,
                        "vote_counts": {"A": 1, "B": 1, "C": 1}, "decision_maker": "A",
                    }


def test_websocket_rejects_bad_tokens_and_events(startup: Path) -> None:
    startup.write_text(
        "participants: [human, ai, ai]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        token = client.post("/join", json={}).json()["participant_token"]
        for path in ("/ws", "/ws?token=wrong", f"/ws?token={token}&token=wrong", f"/ws?token={token}&token="):
            with pytest.raises(WebSocketDisconnect) as error:
                with client.websocket_connect(path):
                    pass
            assert error.value.code == 1008
        with client.websocket_connect(f"/ws?token={token}") as ws:
            assert_state(ws.receive_json(), "discussion", 1)
            for event in (
                "not json", "[]",
                '{"type":"message","round":true,"text":"bad round"}',
                '{"type":"message","round":1.0,"text":"bad round"}',
                '{"type":"vote","candidate":"A","voter":"B"}',
                '{"type":"unknown"}',
            ):
                ws.send_text(event)
                assert ws.receive_json()["type"] == "error"
            ws.send_bytes(b"not text")
            assert ws.receive_json()["type"] == "error"
            ws.send_json({"type": "message", "round": 1, "text": "valid"})
            assert ws.receive_json() == {
                "type": "message", "round": 1, "sender": "A", "text": "valid"
            }
            expire_discussion(client, advance=False)
            ws.send_json({"type": "message", "round": 1, "text": "late"})
            assert_state(ws.receive_json(), "voting", 1)
            assert ws.receive_json()["type"] == "error"


def test_messages_allow_unrestricted_text_and_non_identity_fields(startup: Path) -> None:
    startup.write_text(
        "participants: [human, ai, ai]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        token = client.post("/join", json={}).json()["participant_token"]
        with client.websocket_connect(f"/ws?token={token}") as ws:
            assert_state(ws.receive_json(), "discussion", 1)
            for text in ("", "   ", "x" * 4001):
                ws.send_json({"type": "message", "round": 1, "text": text, "metadata": "ignored"})
                assert ws.receive_json() == {
                    "type": "message", "round": 1, "sender": "A", "text": text
                }
            ws.send_bytes(b'{"type":"message","round":1,"text":"binary JSON"}')
            assert ws.receive_json() == {
                "type": "message", "round": 1, "sender": "A", "text": "binary JSON"
            }
            for field in (
                "sender", "sender_id", "voter", "voter_id", "participant", "participant_id", "player"
            ):
                ws.send_json({"type": "message", "round": 1, "text": "forged", field: "B"})
                assert ws.receive_json()["type"] == "error"


def test_timer_broadcasts_voting_state(startup: Path) -> None:
    startup.write_text(
        "participants: [human, ai, ai]\nrounds: 2\ndiscussion_duration_seconds: 1\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        token = client.post("/join", json={}).json()["participant_token"]
        with client.websocket_connect(f"/ws?token={token}") as ws:
            assert_state(ws.receive_json(), "discussion", 1)
            assert_state(ws.receive_json(), "voting", 1)


def test_configured_duration_applies_to_both_discussions(startup: Path) -> None:
    startup.write_text(
        "participants: [human, ai, ai]\nrounds: 2\ndiscussion_duration_seconds: 17\n",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        before = datetime.now(timezone.utc)
        token = client.post("/join", json={}).json()["participant_token"]
        after = datetime.now(timezone.utc)
        with client.websocket_connect(f"/ws?token={token}") as ws:
            state = ws.receive_json()
            assert_state(state, "discussion", 1)
            deadline = datetime.fromisoformat(state["discussion_ends_at"].replace("Z", "+00:00"))
            assert before + timedelta(seconds=17) <= deadline <= after + timedelta(seconds=17)
            expire_discussion(client)
            assert_state(ws.receive_json(), "voting", 1)
            before = datetime.now(timezone.utc)
            ws.send_json({"type": "vote", "candidate": "A"})
            state = ws.receive_json()
            after = datetime.now(timezone.utc)
            assert_state(state, "discussion", 2)
            deadline = datetime.fromisoformat(state["discussion_ends_at"].replace("Z", "+00:00"))
            assert before + timedelta(seconds=17) <= deadline <= after + timedelta(seconds=17)


def test_failed_connection_does_not_prevent_broadcast_to_other_participants() -> None:
    async def run() -> None:
        hub = ExperimentHub(sessionmaker(), 1, {}, 60)
        failed = MagicMock(spec=WebSocket)
        healthy = MagicMock(spec=WebSocket)
        failed.send_json.side_effect = WebSocketDisconnect()
        hub.connections[failed] = 1
        hub.connections[healthy] = 2
        event = {"type": "message", "round": 1, "sender": "A", "text": "Hello"}

        await hub.publish_message(event)

        assert failed not in hub.connections
        healthy.send_json.assert_awaited_once_with(event)
        failed.close.assert_awaited_once_with(code=1011)

    asyncio.run(run())


def test_uvicorn_handshake_logs_do_not_contain_token(caplog: pytest.LogCaptureFixture) -> None:
    secret = "private-association-token"
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    async def app(scope, receive, send) -> None:
        assert scope["experiment_token"] == secret
        await receive()
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.close", "code": 1000})

    async def run() -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(HideWebSocketQuery(app), log_config=None, lifespan="off")
        )
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.01)
            assert server.started
            async with connect(f"ws://127.0.0.1:{port}/ws?token={secret}"):
                pass
        finally:
            server.should_exit = True
            await task
            listener.close()

    asyncio.run(run())
    assert "WebSocket /ws" in caplog.text
    assert secret not in caplog.text
