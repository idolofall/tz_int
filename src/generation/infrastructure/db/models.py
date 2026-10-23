from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="user")
    tasks: Mapped[list["GenerationTask"]] = relationship(back_populates="user")


class LedgerEntry(Base):
    """Every token movement is exactly one row. Balance is the sum of amounts."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("kind", "reference_id", name="uq_ledger_kind_reference"),
    )

    id: Mapped[object] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[object] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="ledger_entries")


class Model(Base):
    __tablename__ = "models"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    price_tokens: Mapped[int] = mapped_column(Integer, nullable=False)

    legs: Mapped[list["ModelLeg"]] = relationship(
        back_populates="model", order_by="ModelLeg.priority"
    )


class ModelLeg(Base):
    __tablename__ = "model_legs"
    __table_args__ = (
        UniqueConstraint("model_slug", "priority", name="uq_leg_model_priority"),
    )

    id: Mapped[object] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    model_slug: Mapped[str] = mapped_column(
        ForeignKey("models.slug"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    max_ref_images: Mapped[int] = mapped_column(Integer, nullable=False)
    skip_on_moderation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    model: Mapped[Model] = relationship(back_populates="legs")


class GenerationTask(Base):
    __tablename__ = "generation_tasks"

    id: Mapped[object] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[object] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    model_slug: Mapped[str] = mapped_column(ForeignKey("models.slug"), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    ref_images: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    current_leg_id: Mapped[object | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_legs.id")
    )
    result_url: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="tasks")
    current_leg: Mapped[ModelLeg | None] = relationship()
    attempts: Mapped[list["TaskAttempt"]] = relationship(
        back_populates="task", order_by="TaskAttempt.started_at"
    )


class TaskAttempt(Base):
    __tablename__ = "task_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "leg_id", name="uq_attempt_task_leg"),
    )

    id: Mapped[object] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_id: Mapped[object] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generation_tasks.id"),
        nullable=False,
        index=True,
    )
    leg_id: Mapped[object] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_legs.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error_type: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timeout_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    task: Mapped[GenerationTask] = relationship(back_populates="attempts")
    leg: Mapped[ModelLeg] = relationship()
