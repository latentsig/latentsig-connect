"""Persist business card address when available."""
from alembic import op
import sqlalchemy as sa

revision = "0006_lead_address"
down_revision = "0005_other_choice_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("leads")}
    if "address" not in columns:
        op.add_column("leads", sa.Column("address", sa.String(length=500), nullable=True))


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("leads")}
    if "address" in columns:
        op.drop_column("leads", "address")
