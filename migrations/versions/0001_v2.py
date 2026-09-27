"""Frozen initial v2 schema; legacy tables remain untouched."""

from alembic import op

revision = "0001_v2"
down_revision = None


def upgrade():
    op.execute(
        "CREATE TABLE v2_activity (\n\tid INTEGER NOT NULL, \n\tname VARCHAR(128) NOT NULL, \n\tstarts_at DATETIME, \n\tends_at DATETIME, \n\tcancel_until DATETIME, \n\tallow_cancel BOOL NOT NULL, \n\tstate VARCHAR(16) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tPRIMARY KEY (id)\n)"
    )
    op.execute(
        "CREATE TABLE v2_audit (\n\tid INTEGER NOT NULL AUTO_INCREMENT, \n\tactor_id INTEGER NOT NULL, \n\taction VARCHAR(64) NOT NULL, \n\ttarget VARCHAR(128) NOT NULL, \n\tsummary JSON NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)"
    )
    op.execute(
        "CREATE TABLE v2_clubs (\n\tid INTEGER NOT NULL AUTO_INCREMENT, \n\tname VARCHAR(64) NOT NULL, \n\tcategory VARCHAR(64) NOT NULL, \n\tdescription TEXT NOT NULL, \n\tlocation VARCHAR(128) NOT NULL, \n\tschedule VARCHAR(128) NOT NULL, \n\tcover VARCHAR(512) NOT NULL, \n\tcapacity INTEGER NOT NULL, \n\tremaining INTEGER NOT NULL, \n\tactive BOOL NOT NULL, \n\tallowed_majors JSON NOT NULL, \n\tversion INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_quota CHECK (remaining >= 0 AND remaining <= capacity), \n\tUNIQUE (name)\n)"
    )
    op.execute(
        "CREATE TABLE v2_outbox (\n\tid INTEGER NOT NULL AUTO_INCREMENT, \n\tpayload JSON NOT NULL, \n\tdelivered BOOL NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)"
    )
    op.execute("CREATE INDEX ix_v2_outbox_delivered ON v2_outbox (delivered)")
    op.execute(
        "CREATE TABLE v2_users (\n\tid INTEGER NOT NULL AUTO_INCREMENT, \n\tusername VARCHAR(64) NOT NULL, \n\tpassword_hash VARCHAR(255) NOT NULL, \n\tname VARCHAR(64) NOT NULL, \n\t`role` VARCHAR(16) NOT NULL, \n\tmajor VARCHAR(64) NOT NULL, \n\tclass_name VARCHAR(64) NOT NULL, \n\tactive BOOL NOT NULL, \n\tmust_change_password BOOL NOT NULL, \n\ttoken_version INTEGER NOT NULL, \n\tavatar VARCHAR(512) NOT NULL, \n\tphone VARCHAR(32) NOT NULL, \n\temail VARCHAR(254) NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (username)\n)"
    )
    op.execute("CREATE INDEX ix_v2_users_class_name ON v2_users (class_name)")
    op.execute("CREATE INDEX ix_v2_users_major ON v2_users (major)")
    op.execute("CREATE INDEX ix_v2_users_role ON v2_users (`role`)")
    op.execute(
        "CREATE TABLE v2_enrollments (\n\tstudent_id INTEGER NOT NULL, \n\tclub_id INTEGER NOT NULL, \n\tsource VARCHAR(16) NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (student_id), \n\tFOREIGN KEY(student_id) REFERENCES v2_users (id), \n\tFOREIGN KEY(club_id) REFERENCES v2_clubs (id)\n)"
    )
    op.execute("CREATE INDEX ix_v2_enrollments_club_id ON v2_enrollments (club_id)")
    op.execute(
        "CREATE TABLE v2_favorites (\n\tstudent_id INTEGER NOT NULL, \n\tclub_id INTEGER NOT NULL, \n\tPRIMARY KEY (student_id, club_id), \n\tFOREIGN KEY(student_id) REFERENCES v2_users (id), \n\tFOREIGN KEY(club_id) REFERENCES v2_clubs (id)\n)"
    )
    op.execute(
        "CREATE TABLE v2_idempotency (\n\tid INTEGER NOT NULL AUTO_INCREMENT, \n\tuser_id INTEGER NOT NULL, \n\t`key` VARCHAR(64) NOT NULL, \n\tfingerprint VARCHAR(128) NOT NULL, \n\tresponse JSON NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_idempotency UNIQUE (user_id, `key`), \n\tFOREIGN KEY(user_id) REFERENCES v2_users (id)\n)"
    )
    op.execute(
        "CREATE TABLE v2_jobs (\n\tid VARCHAR(36) NOT NULL, \n\tactor_id INTEGER NOT NULL, \n\tkind VARCHAR(32) NOT NULL, \n\tstate VARCHAR(24) NOT NULL, \n\tpayload JSON NOT NULL, \n\tresult JSON NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(actor_id) REFERENCES v2_users (id)\n)"
    )
    op.execute("CREATE INDEX ix_v2_jobs_state ON v2_jobs (state)")


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; use an approved backup.")
