"""Initial migration

Revision ID: 0001_init
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001_init'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create recordings table
    op.create_table(
        'recordings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('egress_id', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('room_name', sa.String(255), nullable=False, index=True),
        sa.Column('matrix_room_id', sa.String(255), nullable=True, index=True),
        sa.Column('file_path', sa.Text(), nullable=True),
        sa.Column('file_url', sa.Text(), nullable=True),
        sa.Column('file_size', sa.String(50), nullable=True),
        sa.Column('duration', sa.String(50), nullable=True),
        sa.Column('started_by', sa.String(255), nullable=True),
        sa.Column('stopped_by', sa.String(255), nullable=True),
        sa.Column('status', sa.Enum('ACTIVE', 'PROCESSING', 'COMPLETED', 'FAILED', 'STOPPED', name='recordingstatus'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('stopped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('metadata', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('recordings')
    op.execute('DROP TYPE IF EXISTS recordingstatus')



