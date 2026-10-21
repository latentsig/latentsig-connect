"""Prevent duplicate interactions when a visitor retries a submission."""
from alembic import op
import sqlalchemy as sa

revision = "0008_interaction_idempotency"
down_revision = "0007_consent_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("interactions")}
    if "idempotency_key" not in columns:
        op.add_column("interactions", sa.Column("idempotency_key", sa.String(length=36), nullable=True))
    if "submission_created" not in columns:
        op.add_column("interactions", sa.Column("submission_created", sa.Boolean(), nullable=True))
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("interactions")}
    if "ix_interactions_idempotency_key" not in indexes:
        op.create_index("ix_interactions_idempotency_key", "interactions", ["idempotency_key"], unique=True)


def downgrade() -> None:
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("interactions")}
    if "ix_interactions_idempotency_key" in indexes:
        op.drop_index("ix_interactions_idempotency_key", table_name="interactions")
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("interactions")}
    if "submission_created" in columns:
        op.drop_column("interactions", "submission_created")
    if "idempotency_key" in columns:
        op.drop_column("interactions", "idempotency_key")
