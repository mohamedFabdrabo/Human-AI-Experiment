import os

from sqlalchemy import DDL, URL
from sqlalchemy.engine import Connection

from models import Base, Experiment


def database_url() -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ["POSTGRES_PORT"]),
        database=os.environ["POSTGRES_DB"],
    )


def initialize_schema(connection: Connection) -> None:
    Base.metadata.create_all(connection)
    connection.execute(
        DDL(
            "ALTER TABLE %(fullname)s ADD COLUMN IF NOT EXISTS "
            "discussion_ends_at timestamp with time zone"
        ).against(Experiment.__table__)
    )
