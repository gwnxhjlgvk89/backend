"""Reset accounts from the previous pinyin policy to literal roster names."""

from alembic import op
import sqlalchemy as sa
from club.initial_passwords import initial_password

revision = "0005_name_password"
down_revision = "0004_plaintext_only"


def upgrade():
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name FROM v2_users ORDER BY id")).all()
    # Validate every account before changing credentials. Requires maintenance.
    values = [{"id": row.id, "password": initial_password(row.name)} for row in rows]
    if values:
        connection.execute(
            sa.text(
                "UPDATE v2_users SET password_plaintext=:password, must_change_password=1, "
                "token_version=token_version+1 WHERE id=:id"
            ),
            values,
        )


def downgrade():
    raise RuntimeError("Password resets are irreversible; use a reviewed data-preserving rollback")
