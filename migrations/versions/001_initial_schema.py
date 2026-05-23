"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-05-23 00:00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # flows: a logical n8n / BuildShip flow definition (one row per flow_id)
    op.create_table(
        "flows",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # flow_versions: a specific (flow_id, prompt, model) tuple. Every prompt
    # change creates a new version. This is how we distinguish "before" and
    # "after" when explaining drift.
    op.create_table(
        "flow_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("flow_id", sa.String(length=128), sa.ForeignKey("flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_provider", sa.String(length=64), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("flow_id", "version", name="uq_flow_versions_flow_version"),
    )
    op.create_index("ix_flow_versions_flow_id", "flow_versions", ["flow_id"])

    # executions: one row per node-level execution.
    # input_hash is a stable hash of the canonicalized input (used for class grouping).
    # output_embedding is the 384-dim vector for cosine similarity.
    op.create_table(
        "executions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("flow_id", sa.String(length=128), sa.ForeignKey("flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flow_version_id", sa.BigInteger(), sa.ForeignKey("flow_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=False),
        sa.Column("output_embedding", Vector(384), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage_json", sa.JSON(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_executions_flow_id", "executions", ["flow_id"])
    op.create_index("ix_executions_input_hash", "executions", ["input_hash"])
    op.create_index("ix_executions_ts", "executions", ["ts"])
    # IVFFlat index for fast nearest-neighbor queries on the output embedding.
    op.execute(
        "CREATE INDEX ix_executions_output_embedding "
        "ON executions USING ivfflat (output_embedding vector_cosine_ops) WITH (lists = 100)"
    )

    # drift_events: one row per detected drift signal.
    op.create_table(
        "drift_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.BigInteger(), sa.ForeignKey("executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flow_id", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),  # "warn" | "fail"
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("baseline_mean", sa.Float(), nullable=True),
        sa.Column("baseline_std", sa.Float(), nullable=True),
        sa.Column("baseline_n", sa.Integer(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_drift_events_flow_id", "drift_events", ["flow_id"])
    op.create_index("ix_drift_events_severity", "drift_events", ["severity"])
    op.create_index("ix_drift_events_ts", "drift_events", ["ts"])


def downgrade() -> None:
    op.drop_table("drift_events")
    op.execute("DROP INDEX IF EXISTS ix_executions_output_embedding")
    op.drop_table("executions")
    op.drop_table("flow_versions")
    op.drop_table("flows")
    op.execute("DROP EXTENSION IF EXISTS vector")
