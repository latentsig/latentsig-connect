"""Allow one optional back-side image per business card interaction."""
from alembic import op
import sqlalchemy as sa

revision = "0002_business_card_back_image"
down_revision = "0001_capture_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("business_cards")}
    for name, column_type in (
        ("back_storage_path", sa.String(1000)),
        ("back_original_filename", sa.String(255)),
        ("back_mime_type", sa.String(80)),
        ("back_file_size", sa.Integer()),
    ):
        if name not in columns:
            op.add_column("business_cards", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("business_cards")}
    for name in ("back_file_size", "back_mime_type", "back_original_filename", "back_storage_path"):
        if name in columns:
            op.drop_column("business_cards", name)
