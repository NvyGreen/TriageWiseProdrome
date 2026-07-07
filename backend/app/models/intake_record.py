from sqlalchemy import Boolean, Column, CheckConstraint, Integer, String, DateTime, ForeignKey, func, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base

class IntakeRecord(Base):
    __tablename__ = "intake_record"

    intake_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient.patient_id", ondelete="CASCADE"), nullable=False, index=True)
    symptoms = Column(JSONB, server_default="{}")
    chief_complaint = Column(String(40), nullable=False)
    heart_rate = Column(Integer)
    blood_pressure_systolic = Column(Integer)
    blood_pressure_diastolic = Column(Integer)
    temperature = Column(Numeric(precision=4, scale=1))
    oxygen_saturation = Column(Integer)
    pain_level = Column(Integer)
    blood_sugar = Column(Numeric(precision=4, scale=1))
    missing_fields = Column(JSONB, server_default="{}")
    source = Column(String(10), nullable=False, server_default="form")
    external_patient_id = Column(String(64))
    actual_outcome = Column(String(20))
    outcome_source = Column(String(10))
    pregnancy_status = Column(String(12))
    pre_existing_conditions = Column(JSONB, server_default="{}")
    arrival_by_ambulance = Column(Boolean)
    recent_ed_visit_72h = Column(Boolean)
    injury_related = Column(Boolean)
    respiration_rate = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


    __table_args__ = (
        CheckConstraint("pain_level >= 0 and pain_level <= 10", name="check_pain_level"),
    )