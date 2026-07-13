from sqlalchemy import Boolean, Column, Integer, String
from app.database import Base

class ScoringRule(Base):
    __tablename__ = "scoring_rule"

    rule_id = Column(Integer, primary_key=True, autoincrement=False)
    factor = Column(String(40), nullable=False)
    threshold = Column(String(60), nullable=False)
    weight = Column(Integer, nullable=False)
    complaint_group = Column(String(40))
    resource_level = Column(String(8))
    esi_anchor = Column(String(60))
    fallback_if_missing = Column(String(120))
    is_active = Column(Boolean, nullable=False, server_default='true')