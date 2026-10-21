"""Record visitor consent with each interaction."""
from alembic import op
import sqlalchemy as sa

revision = "0007_consent_metadata"
down_revision = "0006_lead_address"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("interactions")}
    if "data_processing_consent_at" not in columns:
        op.add_column("interactions", sa.Column("data_processing_consent_at", sa.DateTime(timezone=True), nullable=True))
    if "follow_up_consent_at" not in columns:
        op.add_column("interactions", sa.Column("follow_up_consent_at", sa.DateTime(timezone=True), nullable=True))
    if "consent_notice_version" not in columns:
        op.add_column("interactions", sa.Column("consent_notice_version", sa.String(length=40), nullable=True))
    if "ai_processing_consent_at" not in columns:
        op.add_column("interactions", sa.Column("ai_processing_consent_at", sa.DateTime(timezone=True), nullable=True))
    if "ai_processing_consent_notice_version" not in columns:
        op.add_column("interactions", sa.Column("ai_processing_consent_notice_version", sa.String(length=40), nullable=True))


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("interactions")}
    with op.batch_alter_table("interactions") as batch:
        if "consent_notice_version" in columns:
            batch.drop_column("consent_notice_version")
        if "data_processing_consent_at" in columns:
            batch.drop_column("data_processing_consent_at")
        if "follow_up_consent_at" in columns:
            batch.drop_column("follow_up_consent_at")
        if "ai_processing_consent_at" in columns:
            batch.drop_column("ai_processing_consent_at")
        if "ai_processing_consent_notice_version" in columns:
            batch.drop_column("ai_processing_consent_notice_version")
