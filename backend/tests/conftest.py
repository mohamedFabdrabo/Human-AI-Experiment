from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import main
from config import load_config
from database import database_url
from models import Base


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated PostgreSQL schema rolled back after each test."""
    engine = create_engine(database_url())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                schema = f"test_{uuid4().hex}"
                connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
                connection = connection.execution_options(schema_translate_map={None: schema})
                Base.metadata.create_all(connection)
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    yield db
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session: Session
) -> Path:
    """Run application startup with a temporary config and isolated database."""
    config_path = tmp_path / "config.yml"
    monkeypatch.setattr(main, "load_config", lambda _: load_config(config_path))
    monkeypatch.setattr(main, "create_engine", lambda _: Mock())
    monkeypatch.setattr(main.Base.metadata, "create_all", lambda _: None)
    test_factory = sessionmaker(bind=session.get_bind(), join_transaction_mode="create_savepoint")
    monkeypatch.setattr(main, "sessionmaker", lambda **_: test_factory)
    return config_path
