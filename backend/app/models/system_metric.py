from sqlalchemy import Column, DateTime, func, Integer, Numeric, String
from app.database import Base

class SystemMetric(Base):
    __tablename__ = "system_metric"

    metric_id = Column(Integer, primary_key=True)
    metric_name = Column(String(60), nullable=False)
    metric_value = Column(Numeric(precision=10, scale=3), nullable=False)
    unit = Column(String(16))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)