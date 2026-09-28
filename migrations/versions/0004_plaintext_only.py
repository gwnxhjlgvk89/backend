"""Reset all initial passwords to name pinyin and remove legacy hash storage."""

from alembic import op
import sqlalchemy as sa
from club.initial_passwords import initial_password

revision = "0004_plaintext_only"
down_revision = "0003_plaintext"


def upgrade():
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name FROM v2_users ORDER BY id")).all()
    # Validate every name before changing any credentials. Run in maintenance.
    values = [{"id": row.id, "password": initial_password(row.name)} for row in rows]
    if values:
        connection.execute(
            sa.text(
                "UPDATE v2_users SET password_plaintext=:password, must_change_password=1, "
                "token_version=token_version+1 WHERE id=:id"
            ),
            values,
        )
    op.alter_column("v2_users", "password_plaintext", existing_type=sa.String(72), nullable=False)
    columns = {column["name"] for column in sa.inspect(connection).get_columns("v2_users")}
    if "password_hash" in columns:
        op.drop_column("v2_users", "password_hash")


def downgrade():
    raise RuntimeError(
        "Old backend cannot read plaintext credentials; use a reviewed data-preserving rollback"
    )
