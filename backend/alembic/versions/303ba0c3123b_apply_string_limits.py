"""apply string limits

Revision ID: 303ba0c3123b
Revises: 816e0598eeba
Create Date: 2026-07-07 12:04:34.589529

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '303ba0c3123b'
down_revision: Union[str, Sequence[str], None] = '816e0598eeba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # --- 1. PATIENT TABLE ADJUSTMENTS ---
    op.alter_column('patient', 'name',
               existing_type=sa.VARCHAR(),
               type_=sa.String(length=100),
               existing_nullable=True)
    
    op.alter_column('patient', 'sex',
               existing_type=sa.VARCHAR(),
               type_=sa.String(length=10),
               existing_nullable=True)

    # --- 2. INTAKE_RECORD TABLE ADJUSTMENTS ---
    op.alter_column('intake_record', 'chief_complaint',
               existing_type=sa.VARCHAR(),
               type_=sa.String(length=40),
               existing_nullable=False) # Marked nullable=False per your model
               
    op.alter_column('intake_record', 'source',
               existing_type=sa.VARCHAR(),
               type_=sa.String(length=10),
               existing_nullable=False) # Marked nullable=False per your model
               
    op.alter_column('intake_record', 'external_patient_id',
               existing_type=sa.VARCHAR(),
               type_=sa.String(length=64),
               existing_nullable=True)
               
    op.alter_column('intake_record', 'actual_outcome',
               existing_type=sa.VARCHAR(),
               type_=sa.String(length=20),
               existing_nullable=True)
               
    op.alter_column('intake_record', 'outcome_source',
               existing_type=sa.VARCHAR(),
               type_=sa.String(length=10),
               existing_nullable=True)
               
    op.alter_column('intake_record', 'pregnancy_status',
               existing_type=sa.VARCHAR(),
               type_=sa.String(length=12),
               existing_nullable=True)


def downgrade() -> None:
    # --- REVERT INTAKE_RECORD CHANGES ---
    op.alter_column('intake_record', 'pregnancy_status',
               existing_type=sa.String(length=12),
               type_=sa.VARCHAR(),
               existing_nullable=True)
               
    op.alter_column('intake_record', 'outcome_source',
               existing_type=sa.String(length=10),
               type_=sa.VARCHAR(),
               existing_nullable=True)
               
    op.alter_column('intake_record', 'actual_outcome',
               existing_type=sa.String(length=20),
               type_=sa.VARCHAR(),
               existing_nullable=True)
               
    op.alter_column('intake_record', 'external_patient_id',
               existing_type=sa.String(length=64),
               type_=sa.VARCHAR(),
               existing_nullable=True)
               
    op.alter_column('intake_record', 'source',
               existing_type=sa.String(length=10),
               type_=sa.VARCHAR(),
               existing_nullable=False)
               
    op.alter_column('intake_record', 'chief_complaint',
               existing_type=sa.String(length=40),
               type_=sa.VARCHAR(),
               existing_nullable=False)

    # --- REVERT PATIENT CHANGES ---
    op.alter_column('patient', 'sex',
               existing_type=sa.String(length=10),
               type_=sa.VARCHAR(),
               existing_nullable=True)
               
    op.alter_column('patient', 'name',
               existing_type=sa.String(length=100),
               type_=sa.VARCHAR(),
               existing_nullable=True)
