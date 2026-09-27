"""Add independent v2 tables; leave legacy tables untouched."""
from alembic import op
from club.models import Base

revision = "0001_v2"
down_revision = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError("Destructive downgrade disabled. Restore an approved backup instead.")
