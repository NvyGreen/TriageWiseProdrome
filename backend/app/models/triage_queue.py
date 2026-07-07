from sqlalchemy import Column, DateTime, ForeignKey, func, Integer, Numeric, String
from app.database import Base

class TriageQueue(Base):
    __tablename__ = "triage_queue"

    queue_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    intake_id = Column(Integer, ForeignKey("intake_record.intake_id", ondelete="CASCADE"), nullable=False, index=True)
    severity_id = Column(Integer, ForeignKey("patient_severity.severity_id", ondelete="CASCADE"), nullable=False, index=True)
    severity_score = Column(Numeric(precision=5, scale=1), nullable=False)
    queue_position = Column(Integer)
    status = Column(String(16), nullable=False, server_default="WAITING")
    entered_queue_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)