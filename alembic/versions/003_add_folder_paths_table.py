"""Add folder_paths table for storing validated folder paths.

Revision ID: 003
Revises: 002
Create Date: 2026-04-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'folder_paths',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('is_accessible', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('supported_formats_found', postgresql.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_folder_paths_id'), 'folder_paths', ['id'], unique=False)
    op.create_index(op.f('ix_folder_paths_path'), 'folder_paths', ['path'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_folder_paths_path'), table_name='folder_paths')
    op.drop_index(op.f('ix_folder_paths_id'), table_name='folder_paths')
    op.drop_table('folder_paths')
