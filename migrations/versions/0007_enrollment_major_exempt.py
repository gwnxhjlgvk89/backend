"""Mark operator-approved reservations that are exempt from a club's major restriction."""

from alembic import op
import sqlalchemy as sa

revision = "0007_enrollment_major_exempt"
down_revision = "0006_job_queue_index"


def upgrade():
    op.add_column(
        "v2_enrollments",
        sa.Column("major_exempt", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("v2_enrollments", "major_exempt")
