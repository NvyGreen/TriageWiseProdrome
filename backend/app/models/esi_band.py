from sqlalchemy import Column, Integer, String
from app.dependencies import Base

class ESIBand(Base):
    __tablename__ = "esi_band"

    band_id = Column(Integer, primary_key=True, autoincrement=False)
    min_points = Column(Integer, nullable=False)
    max_points = Column(Integer, nullable=False)
    esi_level = Column(String(8), nullable=False)
    priority = Column(String(10), nullable=False)
    meaning = Column(String(40), nullable=False)