from sqlalchemy import Boolean, CheckConstraint, Column, Integer, ForeignKey, func, Numeric, String, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base

class PatientSeverity(Base):
    __tablename__ = "patient_severity"

    severity_id = Column(Integer, primary_key=True)
    intake_id = Column(Integer, ForeignKey("intake_record.intake_id", ondelete="CASCADE"), nullable=False, index=True)
    severity_score = Column(Numeric(precision=5, scale=1), nullable=False)
    system_ESI = Column(String(8))
    clinician_ESI = Column(String(8))
    score_reason = Column(String)
    fallback_used = Column(Boolean, nullable=False, server_default="false")
    red_flags = Column(JSONB, server_default="{}")
    red_flag_fired = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("severity_score >= 0 and severity_score <= 100", name="check_severity_score"),
    )