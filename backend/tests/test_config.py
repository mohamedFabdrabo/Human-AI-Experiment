import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

import main
from config import load_config


@pytest.mark.parametrize(
    "participants",
    [
        "[human, human, human]",
        "[human, human, ai]",
        "[ai, human, ai]",
    ],
)
def test_loads_supported_conditions(tmp_path: Path, participants: str) -> None:
    """Verify all supported participant conditions load with their settings."""
    path = tmp_path / "config.yml"
    path.write_text(
        f"participants: {participants}\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.participants == participants[1:-1].split(", ")
    assert config.rounds == 2
    assert config.discussion_duration_seconds == 60


@pytest.mark.parametrize(
    "content",
    [
        "participants: [ai, ai, ai]\nrounds: 2\ndiscussion_duration_seconds: 60",
        "participants: [human, ai]\nrounds: 2\ndiscussion_duration_seconds: 60",
        "participants: [human, human, bot]\nrounds: 2\ndiscussion_duration_seconds: 60",
        "participants: [human, human, ai]\nrounds: 3\ndiscussion_duration_seconds: 60",
        "participants: [human, human, ai]\nrounds: 2\ndiscussion_duration_seconds: 0",
        "participants: [human, human, ai]\nrounds: 2\ndiscussion_duration_seconds: true",
        "participants: [human, human, ai]\nrounds: 2",
        "participants: [human, human, ai]\nrounds: 2\ndiscussion_duration_seconds: 60\nextra: 1",
        "",
    ],
)
def test_rejects_invalid_config(tmp_path: Path, content: str) -> None:
    """Verify invalid participant configurations and settings are rejected."""
    path = tmp_path / "config.yml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(path)


def test_reports_missing_or_malformed_file(tmp_path: Path) -> None:
    """Verify missing and malformed configuration files produce clear errors."""
    path = tmp_path / "config.yml"
    with pytest.raises(ValueError, match="Unable to load configuration"):
        load_config(path)
    path.write_text("participants: [human,", encoding="utf-8")
    with pytest.raises(ValueError, match="Unable to load configuration"):
        load_config(path)


def test_invalid_config_prevents_application_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify invalid configuration stops startup before database initialization."""
    path = tmp_path / "config.yml"
    path.write_text(
        "participants: [ai, ai, ai]\nrounds: 2\ndiscussion_duration_seconds: 60\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "load_config", lambda _: load_config(path))

    def unexpected_database_connection(*args: object, **kwargs: object) -> None:
        pytest.fail("database must not be initialized with invalid configuration")

    monkeypatch.setattr(main, "create_engine", unexpected_database_connection)

    async def start_application() -> None:
        async with main.lifespan(main.app):
            pytest.fail("application started with invalid configuration")

    with pytest.raises(ValidationError, match="at least one participant must be human"):
        asyncio.run(start_application())
