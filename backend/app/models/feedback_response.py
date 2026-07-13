from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from app.database import Base

class FeedbackResponse(Base):
    __tablename__ = "feedback_response"

    response_id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("feedback_session.session_id", ondelete="CASCADE"), nullable=False, index=True)
    ai_priority = Column(String(12))
    final_priority = Column(String(12))
    changed_decision = Column(Boolean)
    feedback_text = Column(String)