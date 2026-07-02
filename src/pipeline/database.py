import os
from typing import Generator
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.orm import sessionmaker

# Default to SQLite if DATABASE_URL is not set
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///badminton.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# Create SQLAlchemy engine
if IS_SQLITE:
    connect_args = {"check_same_thread": False}
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=20,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)

def init_db() -> None:
    """Initialize database tables. Used for SQLite environment."""
    from src.pipeline.models import Player, Match, Set, Rally, Shot, ShuttleTrajectory, PlayerPosition, MatchPlayerStats, RallyEmbedding
    import time
    for i in range(10):
        try:
            SQLModel.metadata.create_all(engine)
            break
        except Exception as e:
            if i == 9:
                raise e
            time.sleep(0.3)

def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
