import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("agridirect.database")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agridirect.db")

connect_args = {}
engine_kwargs = {}

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine_kwargs = {"connect_args": connect_args}
elif DATABASE_URL.startswith("mysql"):
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
        "pool_size": 10,
        "max_overflow": 20
    }

try:
    engine = create_engine(DATABASE_URL, **engine_kwargs)
    # Test connection
    with engine.connect() as conn:
        pass
    logger.info(f"Database connected using: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
except Exception as e:
    logger.warning(f"Could not connect to {DATABASE_URL} ({e}). Falling back to SQLite local database.")
    DATABASE_URL = "sqlite:///./agridirect.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """FastAPI database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
