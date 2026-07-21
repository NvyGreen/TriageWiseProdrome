from sqlalchemy import Column, DateTime, func, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from app.dependencies import Base

class IdempotencyKey(Base):
    __tablename__ = "idempotency_key"

    idempotency_key = Column(String(64), primary_key=True)
    request_hash = Column(String(64), nullable=False)
    response_body = Column(JSONB, nullable=False, server_default="{}")
    status_code = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)