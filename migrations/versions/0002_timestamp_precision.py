"""Keep microseconds so opening and closing boundaries are not rounded."""

from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0002_precision"
down_revision = "0001_v2"


def upgrade():
    for table, columns in {
        "v2_activity": ["starts_at", "ends_at", "cancel_until"],
        "v2_enrollments": ["created_at"],
        "v2_idempotency": ["created_at"],
        "v2_outbox": ["created_at"],
        "v2_audit": ["created_at"],
        "v2_jobs": ["created_at", "updated_at"],
    }.items():
        for name in columns:
            op.alter_column(
                table,
                name,
                type_=DATETIME(fsp=6),
                existing_type=DATETIME(),
                existing_nullable=table == "v2_activity",
            )


def downgrade():
    raise RuntimeError("Precision loss rollback disabled")
