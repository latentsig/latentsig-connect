"""Create the lead capture schema and add fields to the original local MVP tables."""
from alembic import op
import sqlalchemy as sa

from app.db.base import Base
from app.db import models  # noqa: F401

revision = "0001_capture_platform"
down_revision = None
branch_labels = None
depends_on = None


def _add_missing_column(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table in inspector.get_table_names() and column.name not in {item["name"] for item in inspector.get_columns(table)}:
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    # The initial UI/API milestone used create_all. These additive changes make
    # this migration safe for that local SQLite database without dropping data.
    _add_missing_column("events", sa.Column("start_date", sa.Date(), nullable=True))
    _add_missing_column("events", sa.Column("end_date", sa.Date(), nullable=True))
    _add_missing_column("events", sa.Column("location", sa.String(180), nullable=True))
    _add_missing_column("events", sa.Column("next_lead_number", sa.Integer(), nullable=False, server_default="1"))
    _add_missing_column("events", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    _add_missing_column("events", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    _add_missing_column("leads", sa.Column("email_type", sa.String(20), nullable=False, server_default="work"))
    _add_missing_column("leads", sa.Column("country", sa.String(2), nullable=True))
    _add_missing_column("interactions", sa.Column("captured_by", sa.String(180), nullable=True))
    _add_missing_column("interactions", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # This baseline includes the pre-migration MVP database. Destructive downgrade
    # is intentionally unsupported; back up the database before schema reversal.
    raise RuntimeError("The initial production schema migration is irreversible.")
