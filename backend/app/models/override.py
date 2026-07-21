from sqlalchemy import Column, DateTime, ForeignKey, func, Integer, String
from app.dependencies import Base

class Override(Base):
    __tablename__ = "override"

    override_id = Column(Integer, primary_key=True)
    intake_id = Column(Integer, ForeignKey("intake_record.intake_id", ondelete="CASCADE"), nullable=False, index=True)
    severity_id = Column(Integer, ForeignKey("patient_severity.severity_id", ondelete="CASCADE"), nullable=False, index=True)
    system_ESI = Column(String(8), nullable=False)
    clinician_ESI=Column(String(8), nullable=False)
    reason_code = Column(String(40), nullable=False)
    note = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)