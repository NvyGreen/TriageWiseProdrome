from sqlalchemy import Column, DateTime, func, Integer, String
from app.dependencies import Base

class FeedbackSession(Base):
    __tablename__ = "feedback_session"

    session_id = Column(Integer, primary_key=True)
    tester_type = Column(String(40))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)