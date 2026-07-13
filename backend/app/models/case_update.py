from sqlalchemy import Column, DateTime, ForeignKey, func, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base

class CaseUpdate(Base):
    __tablename__ = "case_update"

    update_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    intake_id = Column(Integer, ForeignKey("intake_record.intake_id", ondelete="CASCADE"), nullable=False, index=True)
    updated_symptoms = Column(JSONB, server_default="{}")
    updated_vitals = Column(JSONB, server_default="{}")
    reason_for_update = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)