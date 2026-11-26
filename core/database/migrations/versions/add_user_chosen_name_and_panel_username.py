"""add_user_chosen_name_and_panel_username

Revision ID: add_user_chosen_name
Revises: add_remote_user_id
Create Date: 2026-11-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_user_chosen_name'
down_revision: Union[str, Sequence[str], None] = 'add_remote_user_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add chosen_name and normalized_name columns to users table
    op.add_column('users', sa.Column('chosen_name', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('normalized_name', sa.String(length=50), nullable=True))

    # Create partial unique index on normalized_name (only where not null)
    # This enforces global uniqueness across all vendors, case-insensitive
    op.create_index(
        'ix_users_normalized_name_unique',
        'users',
        ['normalized_name'],
        unique=True,
        postgresql_where=sa.text('normalized_name IS NOT NULL')
    )

    # Add CHECK constraint: normalized_name must be lowercase (allows NULL)
    op.create_check_constraint(
        'ck_users_normalized_name_lowercase',
        'users',
        'normalized_name IS NULL OR normalized_name = lower(normalized_name)'
    )

    # Add panel_username column to transactions table
    op.add_column('transactions', sa.Column('panel_username', sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Drop panel_username column from transactions
    op.drop_column('transactions', 'panel_username')

    # Drop CHECK constraint
    op.drop_constraint('ck_users_normalized_name_lowercase', 'users', type_='check')

    # Drop partial unique index
    op.drop_index('ix_users_normalized_name_unique', table_name='users')

    # Drop columns from users
    op.drop_column('users', 'normalized_name')
    op.drop_column('users', 'chosen_name')