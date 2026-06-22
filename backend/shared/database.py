import os
from typing import Generator
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.orm import sessionmaker

# Load DATABASE_URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/badminton")

# SQLite fallback for testing
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# Create SQLAlchemy engine
if IS_SQLITE:
    connect_args = {"check_same_thread": False}
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)

def init_db() -> None:
    """Initialize database tables. Used for SQLite test environment."""
    if IS_SQLITE:
        SQLModel.metadata.create_all(engine)

def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
