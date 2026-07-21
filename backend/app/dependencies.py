from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import get_settings
from app.services.priority_queue import PriorityQueue

DATABASE_URL = get_settings().DATABASE_URL
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
queue = PriorityQueue()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_queue():
    return queue