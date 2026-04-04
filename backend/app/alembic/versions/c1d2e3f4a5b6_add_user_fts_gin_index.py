"""Add GIN index for full-text search on user full_name and email

Revision ID: c1d2e3f4a5b6
Revises: 578553d2161a
Create Date: 2026-04-04 22:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c1d2e3f4a5b6'
down_revision = '578553d2161a'
branch_labels = None
depends_on = None


def upgrade():
    # GIN index on the FTS expression used by the member search endpoint.
    # coalesce(full_name, '') ensures NULL full_name doesn't break the vector.
    op.execute(
        """
        CREATE INDEX ix_user_fts
        ON "user"
        USING GIN (
            to_tsvector('english', coalesce(full_name, '') || ' ' || email)
        )
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS ix_user_fts')
