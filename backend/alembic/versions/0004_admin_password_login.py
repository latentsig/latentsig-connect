"""Add an optional password hash for allowlisted team accounts."""
from alembic import op
import sqlalchemy as sa

revision = "0004_admin_password_login"
down_revision = "0003_reconcile_current_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("users")}
    if "password_hash" not in columns:
        op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
