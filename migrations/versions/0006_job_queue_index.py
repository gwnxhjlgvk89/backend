"""Index the job queue so picking the next job never filesorts payloads."""

from alembic import op

revision = "0006_job_queue_index"
down_revision = "0005_name_password"


def upgrade():
    op.create_index("ix_v2_jobs_state_created_at", "v2_jobs", ["state", "created_at"])


def downgrade():
    op.drop_index("ix_v2_jobs_state_created_at", table_name="v2_jobs")
