"""Initial schema, ledger uniqueness, and the starting model catalog.

Revision ID: 20261023_0001
Revises:
Create Date: 2026-10-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261023_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("reference_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("kind", "reference_id", name="uq_ledger_kind_reference"),
    )
    op.create_index("ix_ledger_entries_user_id", "ledger_entries", ["user_id"])

    op.create_table(
        "models",
        sa.Column("slug", sa.String(length=64), primary_key=True),
        sa.Column("price_tokens", sa.Integer(), nullable=False),
    )
    op.create_table(
        "model_legs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model_slug", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("max_ref_images", sa.Integer(), nullable=False),
        sa.Column(
            "skip_on_moderation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.ForeignKeyConstraint(["model_slug"], ["models.slug"]),
        sa.UniqueConstraint("model_slug", "priority", name="uq_leg_model_priority"),
    )
    op.create_index("ix_model_legs_model_slug", "model_legs", ["model_slug"])

    op.create_table(
        "generation_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_slug", sa.String(length=64), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("ref_images", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_leg_id", postgresql.UUID(as_uuid=True)),
        sa.Column("result_url", sa.Text()),
        sa.Column("error_type", sa.String(length=32)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["model_slug"], ["models.slug"]),
        sa.ForeignKeyConstraint(["current_leg_id"], ["model_legs.id"]),
    )
    op.create_index("ix_generation_tasks_user_id", "generation_tasks", ["user_id"])
    op.create_index("ix_generation_tasks_status", "generation_tasks", ["status"])

    op.create_table(
        "task_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("leg_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=128)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_type", sa.String(length=32)),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["generation_tasks.id"]),
        sa.ForeignKeyConstraint(["leg_id"], ["model_legs.id"]),
        sa.UniqueConstraint("task_id", "leg_id", name="uq_attempt_task_leg"),
    )
    op.create_index("ix_task_attempts_task_id", "task_attempts", ["task_id"])
    op.create_index("ix_task_attempts_status", "task_attempts", ["status"])
    op.create_index("ix_task_attempts_timeout_at", "task_attempts", ["timeout_at"])
    op.create_index("ix_task_attempts_external_id", "task_attempts", ["external_id"])

    models = sa.table(
        "models",
        sa.column("slug", sa.String),
        sa.column("price_tokens", sa.Integer),
    )
    legs = sa.table(
        "model_legs",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("model_slug", sa.String),
        sa.column("provider", sa.String),
        sa.column("priority", sa.Integer),
        sa.column("max_ref_images", sa.Integer),
        sa.column("skip_on_moderation", sa.Boolean),
    )
    op.bulk_insert(
        models,
        [
            {"slug": "image-fast", "price_tokens": 2},
            {"slug": "video-long", "price_tokens": 25},
        ],
    )
    op.bulk_insert(
        legs,
        [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "model_slug": "image-fast",
                "provider": "alpha",
                "priority": 1,
                "max_ref_images": 4,
                "skip_on_moderation": False,
            },
            {
                "id": "11111111-1111-1111-1111-111111111112",
                "model_slug": "image-fast",
                "provider": "beta",
                "priority": 2,
                "max_ref_images": 10,
                "skip_on_moderation": False,
            },
            {
                "id": "22222222-2222-2222-2222-222222222221",
                "model_slug": "video-long",
                "provider": "beta",
                "priority": 1,
                "max_ref_images": 2,
                "skip_on_moderation": False,
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "model_slug": "video-long",
                "provider": "alpha",
                "priority": 2,
                "max_ref_images": 1,
                "skip_on_moderation": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("task_attempts")
    op.drop_table("generation_tasks")
    op.drop_table("model_legs")
    op.drop_table("models")
    op.drop_table("ledger_entries")
    op.drop_table("users")
