from sqlalchemy import Column, DateTime, ForeignKey, func, Integer, Numeric
from app.dependencies import Base

class RetrievalLog(Base):
    __tablename__ = "retrieval_log"

    retrieval_id = Column(Integer, primary_key=True)
    explanation_id = Column(Integer, ForeignKey("ai_explanation.explanation_id", ondelete="CASCADE"), nullable=False, index=True)
    guideline_id = Column(Integer, ForeignKey("guideline_snippet.guideline_id", ondelete="CASCADE"), nullable=False, index=True)
    similarity_score = Column(Numeric(precision=5, scale=4))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)