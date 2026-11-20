from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Experiment(Base):
    __tablename__ = "experiment"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('waiting', 'discussion', 'voting', 'completed')",
            name="ck_experiment_phase",
        ),
        CheckConstraint("current_round IN (1, 2)", name="ck_experiment_round"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    phase: Mapped[str] = mapped_column(Text)
    current_round: Mapped[int | None]
    final_decision_maker_id: Mapped[int | None] = mapped_column(
        ForeignKey("participant.id", name="fk_experiment_final_decision_maker")
    )


class Participant(Base):
    __tablename__ = "participant"
    __table_args__ = (
        CheckConstraint("player_label IN ('A', 'B', 'C')", name="ck_participant_label"),
        CheckConstraint("participant_type IN ('human', 'ai')", name="ck_participant_type"),
        UniqueConstraint("experiment_id", "player_label", name="uq_participant_label"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiment.id"))
    player_label: Mapped[str] = mapped_column(Text)
    participant_type: Mapped[str] = mapped_column(Text)


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (CheckConstraint("round IN (1, 2)", name="ck_message_round"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiment.id"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("participant.id"))
    round: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Vote(Base):
    __tablename__ = "vote"
    __table_args__ = (
        CheckConstraint("round IN (1, 2)", name="ck_vote_round"),
        UniqueConstraint("experiment_id", "voter_id", "round", name="uq_vote_per_round"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiment.id"))
    voter_id: Mapped[int] = mapped_column(ForeignKey("participant.id"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("participant.id"))
    round: Mapped[int]
