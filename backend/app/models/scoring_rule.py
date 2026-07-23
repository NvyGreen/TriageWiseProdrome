from sqlalchemy import Boolean, Column, Integer, Numeric, String
from app.dependencies import Base

class ScoringRule(Base):
    __tablename__ = "scoring_rule"

    rule_id = Column(Integer, primary_key=True, autoincrement=False)
    rule_type = Column(String(10), nullable=False)
    factor = Column(String(40), nullable=False)
    min_bound = Column(Numeric(precision=6, scale=1))
    max_bound = Column(Numeric(precision=6, scale=1))
    units = Column(String(10))
    threshold_display = Column(String(60), nullable=False)
    weight = Column(Integer, nullable=False)
    complaint_group = Column(String(40))
    resource_level = Column(String(8))
    esi_anchor = Column(String(120))
    fallback_if_missing = Column(String(120), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default='true')