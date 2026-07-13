from sqlalchemy import Column, Integer, Numeric, String
from app.database import Base

class VitalRange(Base):
    __tablename__ = "vital_range"

    vital_range_id = Column(Integer, primary_key=True)
    vital_name = Column(String(30), nullable=False)
    age_group = Column(String(20), nullable=False, server_default='adult')
    label = Column(String(20), nullable=False)
    min_value = Column(Numeric(precision=6, scale=2))
    max_value = Column(Numeric(precision=6, scale=2))
    unit = Column(String(12), nullable=False)
    source = Column(String(40))