"""Add threshold_examples table for caching threshold results.

Revision ID: 001
Revises:
Create Date: 2026-04-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'threshold_examples',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('processing_job_id', sa.Integer(), nullable=False),
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('match_count', sa.Integer(), nullable=False),
        sa.Column('sample_matches', postgresql.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['processing_job_id'], ['processing_jobs.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_threshold_examples_processing_job_id'), 'threshold_examples', ['processing_job_id'], unique=False)
    op.create_index(op.f('ix_threshold_examples_threshold'), 'threshold_examples', ['threshold'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_threshold_examples_threshold'), table_name='threshold_examples')
    op.drop_index(op.f('ix_threshold_examples_processing_job_id'), table_name='threshold_examples')
    op.drop_table('threshold_examples')
