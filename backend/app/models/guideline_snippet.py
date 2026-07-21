from sqlalchemy import Column, DateTime, func, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from app.dependencies import Base

class GuidelineSnippet(Base):
    __tablename__ = "guideline_snippet"
    
    guideline_id = Column(Integer, primary_key=True)
    topic = Column(String(80))
    snippet_text = Column(String, nullable=False)
    source_label = Column(String(120))
    tags = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)