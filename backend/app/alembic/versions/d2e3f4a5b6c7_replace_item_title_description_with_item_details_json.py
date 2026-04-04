"""Replace item title/description columns with item_details JSON

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-04 22:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    # Add item_details JSON column (server_default='{}' handles any pre-existing rows)
    op.add_column(
        'item',
        sa.Column('item_details', sa.JSON(), nullable=False, server_default='{}')
    )
    # Drop the old fixed-schema columns
    op.drop_column('item', 'title')
    op.drop_column('item', 'description')


def downgrade():
    # Restore the original fixed-schema columns
    op.add_column(
        'item',
        sa.Column(
            'title',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
            server_default='untitled',
        )
    )
    op.add_column(
        'item',
        sa.Column(
            'description',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        )
    )
    op.drop_column('item', 'item_details')
