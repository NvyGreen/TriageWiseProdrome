from sqlalchemy import Column, Integer, String, Date, DateTime, func
from app.database import Base


class Patient(Base):
    __tablename__ = "patient"

    patient_id = Column(Integer, primary_key=True)
    name = Column(String)
    age = Column(Integer)
    date_of_birth = Column(DateTime(timezone=True))
    sex = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)