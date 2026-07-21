from sqlalchemy import Column, DateTime, ForeignKey, func, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from app.dependencies import Base

class AIExplanation(Base):
    __tablename__ = "ai_explanation"

    explanation_id = Column(Integer, primary_key=True)
    severity_id = Column(Integer, ForeignKey("patient_severity.severity_id", ondelete="CASCADE"), nullable=False, index=True)
    intake_id = Column(Integer, ForeignKey("intake_record.intake_id", ondelete="CASCADE"), nullable=False, index=True)
    explanation_text = Column(String, nullable=False)
    factor_breakdown = Column(JSONB, nullable=False, server_default="{}")
    step = Column(String(8))
    lead_element = Column(String(24))
    model_used = Column(String(40), server_default="rule-based template")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)