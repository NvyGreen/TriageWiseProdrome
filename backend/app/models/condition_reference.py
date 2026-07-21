from sqlalchemy import Column, Integer, String, Numeric
from app.dependencies import Base

class ConditionReference(Base):
    __tablename__ = "condition_reference"

    condition_reference_id = Column(Integer, primary_key=True, autoincrement=False)
    condition = Column(String(80), nullable=False)
    match_type = Column(String(12), nullable=False)
    complaint_key = Column(String(40))
    context_condition = Column(String(80))
    icd10_prefixes = Column(String(80), nullable=False)
    visits = Column(Integer, nullable=False)
    admitted = Column(Integer, nullable=False)
    admit_rate = Column(Numeric(precision=5, scale=4), nullable=False)
    reliable = Column(String(12), nullable=False)
    triage_note = Column(String(120))
    source_label = Column(String(120), nullable=False, server_default="NHAMCS 2022")