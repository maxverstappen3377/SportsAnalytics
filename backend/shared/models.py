from datetime import date, datetime
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from sqlalchemy import String, Date, DateTime, Numeric, Boolean, text
from pgvector.sqlalchemy import Vector

class Player(SQLModel, table=True):
    __tablename__ = "players"

    player_id: UUID = Field(default_factory=uuid4, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    name: str = Field(nullable=False)
    handedness: Optional[str] = Field(default=None, sa_column_kwargs={"sa_column": text("CHECK (handedness IN ('left', 'right'))")})
    country: Optional[str] = Field(default=None)
    external_ref: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"server_default": text("now()")})

class Match(SQLModel, table=True):
    __tablename__ = "matches"

    match_id: UUID = Field(default_factory=uuid4, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    player_a_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id")
    player_b_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id")
    tournament: Optional[str] = Field(default=None)
    match_date: Optional[date] = Field(default=None, sa_column=Column(Date))
    video_uri: Optional[str] = Field(default=None)
    court_calibration: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    source_type: Optional[str] = Field(default=None, sa_column_kwargs={"sa_column": text("CHECK (source_type IN ('broadcast', 'courtside', 'training'))")})
    fps: Optional[float] = Field(default=None, sa_column=Column(Numeric))
    processing_status: str = Field(default="pending", sa_column_kwargs={"server_default": text("'pending'")})
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"server_default": text("now()")})

class Set(SQLModel, table=True):
    __tablename__ = "sets"

    set_id: UUID = Field(default_factory=uuid4, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    match_id: UUID = Field(foreign_key="matches.match_id")
    set_number: int = Field(nullable=False)
    score_a: Optional[int] = Field(default=None)
    score_b: Optional[int] = Field(default=None)
    winner_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id")

class Rally(SQLModel, table=True):
    __tablename__ = "rallies"

    rally_id: UUID = Field(default_factory=uuid4, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    set_id: UUID = Field(foreign_key="sets.set_id")
    rally_number: int = Field(nullable=False)
    server_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id")
    winner_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id")
    rally_length: Optional[int] = Field(default=None)
    start_frame: Optional[int] = Field(default=None)
    end_frame: Optional[int] = Field(default=None)
    start_ts_ms: Optional[int] = Field(default=None, sa_column=Column(Numeric(20, 0))) # to handle BIGINT
    end_ts_ms: Optional[int] = Field(default=None, sa_column=Column(Numeric(20, 0)))   # to handle BIGINT
    end_reason: Optional[str] = Field(default=None)

class Shot(SQLModel, table=True):
    __tablename__ = "shots"

    shot_id: UUID = Field(default_factory=uuid4, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    rally_id: UUID = Field(foreign_key="rallies.rally_id")
    shot_number: int = Field(nullable=False)
    hitter_id: Optional[UUID] = Field(default=None, foreign_key="players.player_id")
    shot_type: str = Field(nullable=False)
    hit_frame: Optional[int] = Field(default=None)
    hit_ts_ms: Optional[int] = Field(default=None, sa_column=Column(Numeric(20, 0)))
    hitter_court_x: Optional[float] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    hitter_court_y: Optional[float] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    receiver_court_x: Optional[float] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    receiver_court_y: Optional[float] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    landing_x: Optional[float] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    landing_y: Optional[float] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    shuttle_speed_est: Optional[float] = Field(default=None, sa_column=Column(Numeric(6, 2)))
    confidence: Optional[float] = Field(default=None, sa_column=Column(Numeric(4, 3)))
    is_winner: bool = Field(default=False, sa_column=Column(Boolean, server_default=text("false")))
    is_error: bool = Field(default=False, sa_column=Column(Boolean, server_default=text("false")))

class ShuttleTrajectory(SQLModel, table=True):
    __tablename__ = "shuttle_trajectory"

    match_id: UUID = Field(foreign_key="matches.match_id", primary_key=True)
    frame_number: int = Field(primary_key=True)
    pixel_x: Optional[float] = Field(default=None, sa_column=Column(Numeric(8, 2)))
    pixel_y: Optional[float] = Field(default=None, sa_column=Column(Numeric(8, 2)))
    court_x: Optional[float] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    court_y: Optional[float] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    visible: bool = Field(default=True, sa_column=Column(Boolean, server_default=text("true")))

class PlayerPosition(SQLModel, table=True):
    __tablename__ = "player_positions"

    match_id: UUID = Field(foreign_key="matches.match_id", primary_key=True)
    frame_number: int = Field(primary_key=True)
    player_id: UUID = Field(foreign_key="players.player_id", primary_key=True)
    court_x: Optional[float] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    court_y: Optional[float] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    pose_keypoints: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

class MatchPlayerStats(SQLModel, table=True):
    __tablename__ = "match_player_stats"

    match_id: UUID = Field(foreign_key="matches.match_id", primary_key=True)
    player_id: UUID = Field(foreign_key="players.player_id", primary_key=True)
    distance_covered_m: Optional[float] = Field(default=0.0, sa_column=Column(Numeric(8, 2)))
    avg_reaction_time_ms: Optional[float] = Field(default=0.0, sa_column=Column(Numeric(8, 2)))
    shot_type_distribution: Optional[Dict[str, int]] = Field(default=None, sa_column=Column(JSON))
    win_rate_by_rally_length: Optional[Dict[str, float]] = Field(default=None, sa_column=Column(JSON))
    avg_rally_length: Optional[float] = Field(default=0.0, sa_column=Column(Numeric(5, 2)))
    pressure_index: Optional[float] = Field(default=0.0, sa_column=Column(Numeric(4, 3)))
    computed_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"server_default": text("now()")})

class RallyEmbedding(SQLModel, table=True):
    __tablename__ = "rally_embeddings"

    rally_id: UUID = Field(foreign_key="rallies.rally_id", primary_key=True)
    embedding: Any = Field(sa_column=Column(Vector(256)))
