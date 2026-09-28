"""Add the staging column before the full 0004 plaintext cutover."""

from alembic import op
import sqlalchemy as sa

revision = "0003_plaintext"
down_revision = "0002_precision"


def upgrade():
    op.add_column("v2_users", sa.Column("password_plaintext", sa.String(72), nullable=True))


def downgrade():
    raise RuntimeError("Plaintext credentials cannot be used by the old backend; convert before rollback")
