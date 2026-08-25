from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, func, Index, Integer, String
from app.dependencies import Base

class TriageQueue(Base):
    __tablename__ = "triage_queue"

    queue_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    intake_id = Column(Integer, ForeignKey("intake_record.intake_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    severity_id = Column(Integer, ForeignKey("patient_severity.severity_id", ondelete="CASCADE"), nullable=False, index=True)
    esi_band = Column(Integer, nullable=False)
    flag_tier = Column(Integer, nullable=False)
    arrival_time = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(16), nullable=False, server_default="WAITING", index=True)
    entered_queue_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("esi_band >= 1 and esi_band <= 5", name="check_esi_band"),
        CheckConstraint("flag_tier >= 1 and flag_tier <= 3", name="check_flag_tier"),
        Index("ix_triage_queue_sort_key", "esi_band", "flag_tier", "arrival_time", "intake_id")
    )