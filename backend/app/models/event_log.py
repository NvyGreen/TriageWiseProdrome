from sqlalchemy import Column, DateTime, ForeignKey, func, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from app.dependencies import Base

class EventLog(Base):
    __tablename__ = "event_log"

    log_id = Column(Integer, primary_key=True)
    event_type = Column(String(40), nullable=False)
    patient_id = Column(Integer, ForeignKey("patient.patient_id", ondelete="SET NULL"), nullable=True, index=True)
    intake_id = Column(Integer, ForeignKey("intake_record.intake_id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)