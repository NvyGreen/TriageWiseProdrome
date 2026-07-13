from sqlalchemy import Boolean, Column, Integer, String
from app.database import Base

class RedFlagRule(Base):
    __tablename__ = "red_flag_rule"
    
    flag_id = Column(Integer, primary_key=True, autoincrement=False)
    trigger_pattern = Column(String(200), nullable=False)
    flag_type = Column(String(20), nullable=False)
    flag_tier = Column(Integer, nullable=False)
    message = Column(String(160), nullable=False)
    rationale = Column(String)
    evidence_source = Column(String(120), nullable=False)
    outcome_validated = Column(String(20), nullable=False)
    requires_field = Column(String(120))
    is_active = Column(Boolean, nullable=False, server_default='true')