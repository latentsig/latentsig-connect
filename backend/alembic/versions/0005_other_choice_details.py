"""Store separate Other answers for interest and discussion."""
from alembic import op
import sqlalchemy as sa

revision = "0005_other_choice_details"
down_revision = "0004_admin_password_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("interactions")}
    if "other_interest_details" not in columns:
        op.add_column("interactions", sa.Column("other_interest_details", sa.Text(), nullable=True))
    if "other_intent_details" not in columns:
        op.add_column("interactions", sa.Column("other_intent_details", sa.Text(), nullable=True))


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("interactions")}
    if "other_intent_details" in columns:
        op.drop_column("interactions", "other_intent_details")
    if "other_interest_details" in columns:
        op.drop_column("interactions", "other_interest_details")
