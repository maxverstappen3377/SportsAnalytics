import os
from datetime import date, datetime, timezone
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from sqlalchemy import String, Date, DateTime, Numeric, Float, Boolean, text

# Check if using SQLite based on environment variable
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///badminton.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

class Player(SQLModel, table=True):
    __tablename__ = "players"

    player_id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(nullable=False)
    handedness: Optional[str] = Field(default=None)
    country: Optional[str] = Field(default=None)
    external_ref: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Match(SQLModel, table=True):
    __tablename__ = "matches"

    match_id: UUID = Field(default_factory=uuid4, primary_key=True)
    player_a_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id", index=True)
    player_b_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id", index=True)
    tournament: Optional[str] = Field(default=None)
    match_date: Optional[date] = Field(default=None, sa_column=Column(Date))
    video_uri: Optional[str] = Field(default=None)
    court_calibration: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    source_type: Optional[str] = Field(default=None)
    fps: Optional[float] = Field(default=None, sa_column=Column(Float))
    processing_status: str = Field(default="pending")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Set(SQLModel, table=True):
    __tablename__ = "sets"

    set_id: UUID = Field(default_factory=uuid4, primary_key=True)
    match_id: UUID = Field(foreign_key="matches.match_id", index=True)
    set_number: int = Field(nullable=False)
    score_a: Optional[int] = Field(default=None)
    score_b: Optional[int] = Field(default=None)
    winner_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id", index=True)

class Rally(SQLModel, table=True):
    __tablename__ = "rallies"

    rally_id: UUID = Field(default_factory=uuid4, primary_key=True)
    set_id: UUID = Field(foreign_key="sets.set_id")
    rally_number: int = Field(nullable=False)
    server_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id", index=True)
    winner_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id", index=True)
    rally_length: Optional[int] = Field(default=None)
    start_frame: Optional[int] = Field(default=None)
    end_frame: Optional[int] = Field(default=None)
    start_ts_ms: Optional[int] = Field(default=None, sa_column=Column(Numeric(20, 0)))
    end_ts_ms: Optional[int] = Field(default=None, sa_column=Column(Numeric(20, 0)))
    end_reason: Optional[str] = Field(default=None)
    shap_explanation: Optional[str] = Field(default=None)

class Shot(SQLModel, table=True):
    __tablename__ = "shots"

    shot_id: UUID = Field(default_factory=uuid4, primary_key=True)
    rally_id: UUID = Field(foreign_key="rallies.rally_id")
    shot_number: int = Field(nullable=False)
    hitter_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id")
    shot_type: str = Field(nullable=False)
    hit_frame: Optional[int] = Field(default=None)
    hit_ts_ms: Optional[int] = Field(default=None, sa_column=Column(Numeric(20, 0)))
    hitter_court_x: Optional[float] = Field(default=None, sa_column=Column(Float))
    hitter_court_y: Optional[float] = Field(default=None, sa_column=Column(Float))
    receiver_court_x: Optional[float] = Field(default=None, sa_column=Column(Float))
    receiver_court_y: Optional[float] = Field(default=None, sa_column=Column(Float))
    landing_x: Optional[float] = Field(default=None, sa_column=Column(Float))
    landing_y: Optional[float] = Field(default=None, sa_column=Column(Float))
    shuttle_speed_est: Optional[float] = Field(default=None, sa_column=Column(Float))
    confidence: Optional[float] = Field(default=None, sa_column=Column(Float))
    is_winner: bool = Field(default=False, sa_column=Column(Boolean))
    is_error: bool = Field(default=False, sa_column=Column(Boolean))

class ShuttleTrajectory(SQLModel, table=True):
    __tablename__ = "shuttle_trajectory"

    match_id: UUID = Field(foreign_key="matches.match_id", primary_key=True)
    frame_number: int = Field(primary_key=True)
    pixel_x: Optional[float] = Field(default=None, sa_column=Column(Float))
    pixel_y: Optional[float] = Field(default=None, sa_column=Column(Float))
    court_x: Optional[float] = Field(default=None, sa_column=Column(Float))
    court_y: Optional[float] = Field(default=None, sa_column=Column(Float))
    visible: bool = Field(default=True, sa_column=Column(Boolean))
    speed: Optional[float] = Field(default=None, sa_column=Column(Float))
    event: Optional[str] = Field(default=None, sa_column=Column(String))
    vx: Optional[float] = Field(default=None, sa_column=Column(Float))
    vy: Optional[float] = Field(default=None, sa_column=Column(Float))
    vz: Optional[float] = Field(default=None, sa_column=Column(Float))
    ax: Optional[float] = Field(default=None, sa_column=Column(Float))
    ay: Optional[float] = Field(default=None, sa_column=Column(Float))
    az: Optional[float] = Field(default=None, sa_column=Column(Float))
    landing_x_pred: Optional[float] = Field(default=None, sa_column=Column(Float))
    landing_y_pred: Optional[float] = Field(default=None, sa_column=Column(Float))
    time_to_landing: Optional[float] = Field(default=None, sa_column=Column(Float))

class PlayerPosition(SQLModel, table=True):
    __tablename__ = "player_positions"

    match_id: UUID = Field(foreign_key="matches.match_id", primary_key=True)
    frame_number: int = Field(primary_key=True)
    player_id: UUID = Field(foreign_key="players.player_id", primary_key=True)
    court_x: Optional[float] = Field(default=None, sa_column=Column(Float))
    court_y: Optional[float] = Field(default=None, sa_column=Column(Float))
    pose_keypoints: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    com_x: Optional[float] = Field(default=None, sa_column=Column(Float))
    com_y: Optional[float] = Field(default=None, sa_column=Column(Float))
    footwork_pattern: Optional[str] = Field(default=None, sa_column=Column(String))
    predicted_x_05s: Optional[float] = Field(default=None, sa_column=Column(Float))
    predicted_y_05s: Optional[float] = Field(default=None, sa_column=Column(Float))

class MatchPlayerStats(SQLModel, table=True):
    __tablename__ = "match_player_stats"

    match_id: UUID = Field(foreign_key="matches.match_id", primary_key=True)
    player_id: UUID = Field(foreign_key="players.player_id", primary_key=True)
    distance_covered_m: Optional[float] = Field(default=0.0, sa_column=Column(Float))
    avg_reaction_time_ms: Optional[float] = Field(default=0.0, sa_column=Column(Float))
    shot_type_distribution: Optional[Dict[str, int]] = Field(default=None, sa_column=Column(JSON))
    win_rate_by_rally_length: Optional[Dict[str, float]] = Field(default=None, sa_column=Column(JSON))
    avg_rally_length: Optional[float] = Field(default=0.0, sa_column=Column(Float))
    pressure_index: Optional[float] = Field(default=0.0, sa_column=Column(Float))
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# Vector similarity fallback setup
if IS_SQLITE:
    class RallyEmbedding(SQLModel, table=True):
        __tablename__ = "rally_embeddings"
        rally_id: UUID = Field(foreign_key="rallies.rally_id", primary_key=True)
        embedding: str = Field(default=None) # Stored as JSON string
else:
    try:
        from pgvector.sqlalchemy import Vector
        class RallyEmbedding(SQLModel, table=True):
            __tablename__ = "rally_embeddings"
            rally_id: UUID = Field(foreign_key="rallies.rally_id", primary_key=True)
            embedding: Any = Field(sa_column=Column(Vector(256)))
    except ImportError:
        class RallyEmbedding(SQLModel, table=True):
            __tablename__ = "rally_embeddings"
            rally_id: UUID = Field(foreign_key="rallies.rally_id", primary_key=True)
            embedding: str = Field(default=None)
