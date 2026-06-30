from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import date, datetime

# Token Schemas
class Token(BaseModel):
    access_token: str
    token_type: str

class LoginRequest(BaseModel):
    username: str
    password: str

# Match Schemas
class MatchCreate(BaseModel):
    player_a_id: UUID
    player_b_id: UUID
    tournament: Optional[str] = None
    match_date: Optional[date] = None
    source_type: str = Field(description="Must be 'broadcast', 'courtside', or 'training'")
    video_url: Optional[str] = None

class MatchResponse(BaseModel):
    match_id: UUID
    player_a_id: UUID
    player_b_id: UUID
    tournament: Optional[str]
    match_date: Optional[date]
    video_uri: Optional[str]
    court_calibration: Optional[Dict[str, Any]]
    source_type: Optional[str]
    fps: Optional[float]
    processing_status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class MatchStatusResponse(BaseModel):
    status: str
    progress: int
    error: Optional[str] = None

# Shot Schemas
class ShotResponse(BaseModel):
    shot_id: UUID
    rally_id: UUID
    shot_number: int
    hitter_id: UUID
    shot_type: str
    hit_frame: Optional[int]
    hit_ts_ms: Optional[int]
    hitter_court_x: Optional[float]
    hitter_court_y: Optional[float]
    receiver_court_x: Optional[float]
    receiver_court_y: Optional[float]
    landing_x: Optional[float]
    landing_y: Optional[float]
    shuttle_speed_est: Optional[float]
    confidence: Optional[float]
    is_winner: bool
    is_error: bool

    model_config = ConfigDict(from_attributes=True)

class PaginatedShots(BaseModel):
    total: int
    offset: int
    limit: int
    items: List[ShotResponse]

# Rally Schemas
class RallyResponse(BaseModel):
    rally_id: UUID
    set_id: UUID
    rally_number: int
    server_id: UUID
    winner_id: UUID
    rally_length: Optional[int]
    start_frame: Optional[int]
    end_frame: Optional[int]
    start_ts_ms: Optional[int]
    end_ts_ms: Optional[int]
    end_reason: Optional[str]
    shap_explanation: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class RallyDetailResponse(BaseModel):
    rally: RallyResponse
    shots: List[ShotResponse]

# Stats Schemas
class StatsResponse(BaseModel):
    match_id: UUID
    player_id: UUID
    distance_covered_m: float
    avg_reaction_time_ms: float
    shot_type_distribution: Dict[str, int]
    win_rate_by_rally_length: Dict[str, float]
    avg_rally_length: float
    pressure_index: float
    computed_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Heatmap Schemas
class HeatmapResponse(BaseModel):
    grid: List[List[float]]
    bounds: Dict[str, float]

# Win Probability Schemas
class WinProbabilityPoint(BaseModel):
    rally_id: str
    win_prob_a: float
    win_prob_b: float
    score_a: Optional[int] = None
    score_b: Optional[int] = None
    shap_explanation: Optional[str] = None

class WinProbabilityTimeline(BaseModel):
    timeline: List[WinProbabilityPoint]

# Next Shot Schemas
class NextShotRequest(BaseModel):
    rally_id: UUID
    up_to_shot_number: int

class NextShotPredictionItem(BaseModel):
    shot_type: str
    probability: float

class NextShotPredictionResponse(BaseModel):
    predicted_shot_type: str
    confidence: float
    top_3: List[NextShotPredictionItem]

# Prescriptive Schemas
class RecommendationItem(BaseModel):
    category: str = Field(description="tactical, technical, physical")
    priority: int
    summary: str
    supporting_metric: str
    estimated_impact: str

class CoachingResponse(BaseModel):
    recommendations: List[RecommendationItem]
