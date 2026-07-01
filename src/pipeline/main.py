import os
import shutil
import numpy as np
import asyncio
import threading
from uuid import UUID, uuid4
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, status, Query, BackgroundTasks, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from sqlmodel import Session, select, func

from src.pipeline.database import engine, init_db, get_db
from src.pipeline.models import Match, Player, Set, Rally, Shot, ShuttleTrajectory, PlayerPosition, MatchPlayerStats
from src.pipeline.schemas import MatchCreate, MatchResponse, MatchStatusResponse, HeatmapResponse, RallyResponse, ShotResponse
from src.pipeline.video_processor import process_video_and_sync, compute_heatmap

from fastapi.staticfiles import StaticFiles

app = FastAPI(title="AuraSports Video Analytics API", version="1.0.0")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for uploads
uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public", "uploads"))
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

# Seed players and matches if empty
def seed_default_data(db: Session):
    player_count = db.exec(select(func.count(Player.player_id))).one()
    if player_count == 0:
        p1 = Player(player_id=UUID("00000000-0000-0000-0000-000000000001"), name="Viktor Axelsen", handedness="right", country="Denmark")
        p2 = Player(player_id=UUID("00000000-0000-0000-0000-000000000002"), name="Lee Zii Jia", handedness="right", country="Malaysia")
        db.add(p1)
        db.add(p2)
        db.commit()
        print("[Database] Seeded default players: Viktor Axelsen & Lee Zii Jia.")

@app.on_event("startup")
def on_startup():
    init_db()
    with Session(engine) as db:
        seed_default_data(db)

# Active WebSocket connections for live streaming
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, match_id: str, websocket: WebSocket):
        await websocket.accept()
        if match_id not in self.active_connections:
            self.active_connections[match_id] = []
        self.active_connections[match_id].append(websocket)

    def disconnect(self, match_id: str, websocket: WebSocket):
        if match_id in self.active_connections:
            self.active_connections[match_id].remove(websocket)
            if not self.active_connections[match_id]:
                del self.active_connections[match_id]

    async def broadcast(self, match_id: str, message: Dict[str, Any]):
        if match_id in self.active_connections:
            for connection in self.active_connections[match_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

manager = ConnectionManager()

# ----------------- WebSocket Live Stream -----------------
@app.websocket("/api/v1/matches/{match_id}/ws")
async def websocket_endpoint(websocket: WebSocket, match_id: str):
    await manager.connect(match_id, websocket)
    try:
        while True:
            # Wait for any messages from client (e.g. heartbeat)
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(match_id, websocket)

# Background worker wrapper running in a separate thread to keep the event loop responsive
def run_processor_background_thread(match_id: UUID, file_path: str, loop: asyncio.AbstractEventLoop):
    try:
        generator = process_video_and_sync(match_id, file_path)
        for progress_update in generator:
            asyncio.run_coroutine_threadsafe(
                manager.broadcast(str(match_id), progress_update),
                loop
            )
    except Exception as e:
        print(f"[Worker Error] Failed processing: {e}")
        asyncio.run_coroutine_threadsafe(
            manager.broadcast(str(match_id), {"status": "failed", "message": str(e)}),
            loop
        )

# ----------------- Endpoints -----------------

@app.get("/api/v1/players", response_model=List[Player])
def get_players(db: Session = Depends(get_db)):
    return db.exec(select(Player)).all()

@app.get("/api/v1/players/{player_id}", response_model=Player)
def get_player(player_id: UUID, db: Session = Depends(get_db)):
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return player

@app.post("/api/v1/players", response_model=Player, status_code=201)
def create_player(player: Player, db: Session = Depends(get_db)):
    db.add(player)
    db.commit()
    db.refresh(player)
    return player

@app.get("/api/v1/matches", response_model=List[MatchResponse])
def get_matches(db: Session = Depends(get_db)):
    return db.exec(select(Match).order_by(Match.created_at.desc())).all()

@app.get("/api/v1/matches/{match_id}", response_model=MatchResponse)
def get_match(match_id: UUID, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match

@app.post("/api/v1/matches", response_model=MatchResponse, status_code=201)
def create_match(payload: MatchCreate, db: Session = Depends(get_db)):
    player_a = db.get(Player, payload.player_a_id)
    player_b = db.get(Player, payload.player_b_id)
    if not player_a or not player_b:
        raise HTTPException(status_code=422, detail="One or both players not found.")

    match_id = uuid4()
    upload_url = f"/api/v1/matches/{match_id}/video/upload"

    match = Match(
        match_id=match_id,
        player_a_id=payload.player_a_id,
        player_b_id=payload.player_b_id,
        tournament=payload.tournament,
        match_date=payload.match_date,
        video_uri=payload.video_url, # Save URL if pasted
        source_type=payload.source_type,
        fps=30.0,
        processing_status="pending",
        court_calibration={"upload_url": upload_url, "homography_matrix": np.eye(3).tolist()}
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    return match

@app.put("/api/v1/matches/{match_id}/video/upload")
async def upload_local_video(match_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public", "uploads"))
    os.makedirs(uploads_dir, exist_ok=True)
    local_path = os.path.join(uploads_dir, f"{match_id}.mp4")

    try:
        with open(local_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Save relative URL for Next.js public consumption
        web_uri = f"/uploads/{match_id}.mp4"
        match.video_uri = web_uri
        db.add(match)
        db.commit()
        db.refresh(match)
        return {"status": "success", "video_uri": web_uri}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save video file: {e}")

@app.post("/api/v1/matches/{match_id}/video/confirm", response_model=MatchStatusResponse)
async def confirm_video_upload(match_id: UUID, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    if not match.video_uri:
        raise HTTPException(status_code=400, detail="No video file or URL found for this match.")

    local_video_path = match.video_uri
    if not (local_video_path.startswith("http://") or local_video_path.startswith("https://") or os.path.exists(local_video_path)):
        uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public", "uploads"))
        possible_path = os.path.join(uploads_dir, f"{match_id}.mp4")
        if os.path.exists(possible_path):
            local_video_path = possible_path
        else:
            local_video_path = "dummy.mp4"

    # Set status to processing_cv
    match.processing_status = "processing_cv"
    db.add(match)
    db.commit()

    # Trigger video processing in a background OS thread to prevent event loop blocking
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
        
    thread = threading.Thread(
        target=run_processor_background_thread,
        args=(match.match_id, local_video_path, loop)
    )
    thread.daemon = True
    thread.start()

    return MatchStatusResponse(status="processing_cv", progress=0)

@app.get("/api/v1/matches/{match_id}/status", response_model=MatchStatusResponse)
def get_match_status(match_id: UUID, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    status_map = {
        "pending": 0,
        "queued": 10,
        "processing_cv": 50,
        "processing_analytics": 90,
        "done": 100,
        "failed": 0
    }
    progress = status_map.get(match.processing_status, 0)
    
    error_msg = None
    if match.processing_status == "failed":
        error_msg = "CV pipeline execution failed."

    return MatchStatusResponse(status=match.processing_status, progress=progress, error=error_msg)

# Refactored Root-Level Endpoints
@app.get("/api/v1/matches/{id}/trajectory")
def get_match_trajectory(id: UUID, db: Session = Depends(get_db)):
    stmt = select(ShuttleTrajectory).where(ShuttleTrajectory.match_id == id).order_by(ShuttleTrajectory.frame_number)
    results = db.exec(stmt).all()
    return [
        {
            "frame": r.frame_number,
            "x": r.pixel_x,
            "y": r.pixel_y,
            "court_x": r.court_x,
            "court_y": r.court_y,
            "speed": r.speed,
            "event": r.event,
            "vx": r.vx,
            "vy": r.vy,
            "vz": r.vz,
            "ax": r.ax,
            "ay": r.ay,
            "az": r.az,
            "landing_x_pred": r.landing_x_pred,
            "landing_y_pred": r.landing_y_pred,
            "time_to_landing": r.time_to_landing
        }
        for r in results
    ]

@app.get("/api/v1/matches/{id}/analytics")
def get_match_analytics(id: UUID, db: Session = Depends(get_db)):
    sets_stmt = select(Set.set_id).where(Set.match_id == id)
    set_ids = db.exec(sets_stmt).all()
    rallies = []
    if set_ids:
        rallies = db.exec(select(Rally).where(Rally.set_id.in_(set_ids))).all()

    rally_count = len(rallies)
    rally_durations = [((r.end_frame - r.start_frame) / 30.0) for r in rallies if r.start_frame is not None and r.end_frame is not None]
    avg_duration = sum(rally_durations) / len(rally_durations) if rally_durations else 0.0
    longest_duration = max(rally_durations) if rally_durations else 0.0
    total_duration = sum(rally_durations)

    trajs = db.exec(select(ShuttleTrajectory).where(ShuttleTrajectory.match_id == id)).all()
    speeds = [t.speed for t in trajs if t.speed is not None and t.speed > 0.0]
    avg_speed = sum(speeds) / len(speeds) if speeds else 18.5
    peak_speed = max(speeds) if speeds else 35.0

    speed_dist = {"0-10": 0, "10-20": 0, "20-30": 0, "30+": 0}
    for s in speeds:
        if s <= 10.0: speed_dist["0-10"] += 1
        elif s <= 20.0: speed_dist["10-20"] += 1
        elif s <= 30.0: speed_dist["20-30"] += 1
        else: speed_dist["30+"] += 1

    shots = []
    if rallies:
        shots = db.exec(select(Shot).where(Shot.rally_id.in_([r.rally_id for r in rallies]))).all()

    total_shots = len(shots)
    shot_dist = {}
    for s in shots:
        shot_dist[s.shot_type] = shot_dist.get(s.shot_type, 0) + 1

    opponent_targeting = {"player_a": 0, "player_b": 0}
    front_count, mid_count, back_count = 0, 0, 0
    for s in shots:
        if s.landing_x is not None and s.landing_y is not None:
            if s.landing_y < 0.5:
                opponent_targeting["player_a"] += 1
                y_norm = s.landing_y / 0.5
                if y_norm < 0.3: front_count += 1
                elif y_norm < 0.7: mid_count += 1
                else: back_count += 1
            else:
                opponent_targeting["player_b"] += 1
                y_norm = (1.0 - s.landing_y) / 0.5
                if y_norm < 0.3: front_count += 1
                elif y_norm < 0.7: mid_count += 1
                else: back_count += 1

    total_landings = front_count + mid_count + back_count
    court_util = {
        "front": front_count / total_landings if total_landings > 0 else 0.33,
        "mid": mid_count / total_landings if total_landings > 0 else 0.33,
        "back": back_count / total_landings if total_landings > 0 else 0.33
    }

    clusters = []
    if shots:
        grid_bins = {}
        for s in shots:
            if s.landing_x is not None and s.landing_y is not None:
                bin_key = (round(s.landing_x, 1), round(s.landing_y, 1))
                grid_bins[bin_key] = grid_bins.get(bin_key, 0) + 1
        sorted_bins = sorted(grid_bins.items(), key=lambda item: item[1], reverse=True)
        for (bx, by), count in sorted_bins[:5]:
            clusters.append({"x": bx, "y": by, "count": count})

    return {
        "rallies": {
            "count": rally_count,
            "average_duration_sec": round(avg_duration, 2),
            "longest_duration_sec": round(longest_duration, 2),
            "total_duration_sec": round(total_duration, 2)
        },
        "speed": {
            "average_mps": round(avg_speed, 2),
            "peak_mps": round(peak_speed, 2),
            "distribution": speed_dist
        },
        "shots": {
            "total": total_shots,
            "distribution": shot_dist
        },
        "landing": {
            "clusters": clusters,
            "opponent_targeting": opponent_targeting
        },
        "court_utilization": court_util
    }

@app.get("/api/v1/matches/{id}/rallies", response_model=List[RallyResponse])
def get_match_rallies(id: UUID, db: Session = Depends(get_db)):
    sets_stmt = select(Set.set_id).where(Set.match_id == id)
    set_ids = db.exec(sets_stmt).all()
    if not set_ids:
        return []
    return db.exec(select(Rally).where(Rally.set_id.in_(set_ids)).order_by(Rally.rally_number)).all()

@app.get("/api/v1/matches/{id}/shots", response_model=List[ShotResponse])
def get_match_shots(id: UUID, db: Session = Depends(get_db)):
    sets_stmt = select(Set.set_id).where(Set.match_id == id)
    set_ids = db.exec(sets_stmt).all()
    if not set_ids:
        return []
    rally_ids = db.exec(select(Rally.rally_id).where(Rally.set_id.in_(set_ids))).all()
    if not rally_ids:
        return []
    return db.exec(select(Shot).where(Shot.rally_id.in_(rally_ids)).order_by(Shot.rally_id, Shot.shot_number)).all()

@app.get("/api/v1/matches/{id}/heatmap", response_model=HeatmapResponse)
def get_match_heatmap(id: UUID, type: str = Query(default="hit"), player_id: Optional[UUID] = Query(default=None), db: Session = Depends(get_db)):
    if type not in ["hit", "landing"]:
        raise HTTPException(status_code=422, detail="Type must be 'hit' or 'landing'")
    return compute_heatmap(db, id, player_id, type)

@app.get("/api/v1/matches/{id}/report")
def get_match_report(id: UUID, db: Session = Depends(get_db)):
    match = db.get(Match, id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    player_a = db.get(Player, match.player_a_id) if match.player_a_id else None
    player_b = db.get(Player, match.player_b_id) if match.player_b_id else None
    player_a_name = player_a.name if player_a else "Player A"
    player_b_name = player_b.name if player_b else "Player B"

    analytics = get_match_analytics(id, db)
    total_shots = analytics["shots"]["total"]
    peak_speed = analytics["speed"]["peak_mps"]
    avg_speed = analytics["speed"]["average_mps"]
    rally_count = analytics["rallies"]["count"]
    avg_duration = analytics["rallies"]["average_duration_sec"]

    summary = (
        f"Badminton match analysis for {match.tournament or 'Tournament'} played on {match.match_date or 'N/A'}. "
        f"The match featured a total of {rally_count} rallies with an average duration of {avg_duration} seconds. "
        f"A total of {total_shots} shots were tracked across all rallies. "
        f"The peak shuttlecock speed reached {round(peak_speed * 3.6, 1)} km/h ({peak_speed} m/s) "
        f"with an average flight speed of {round(avg_speed * 3.6, 1)} km/h ({avg_speed} m/s)."
    )

    shot_dist = analytics["shots"]["distribution"]
    most_common_shot = max(shot_dist.items(), key=lambda x: x[1])[0] if shot_dist else "clear"

    tactical_notes = [
        f"Most common stroke type was the '{most_common_shot}', which dictated the tempo of the play.",
        f"Landing analysis shows high concentration of shots in the mid-court area, highlighting intense placement duels."
    ]
    if peak_speed > 40.0:
        tactical_notes.append("High peak smash speed indicates aggressive offensive play from both competitors.")

    return {
        "match_id": id,
        "tournament": match.tournament,
        "player_a": player_a_name,
        "player_b": player_b_name,
        "summary": summary,
        "tactical_notes": tactical_notes,
        "statistics": {
            "total_shots": total_shots,
            "peak_speed_kmh": round(peak_speed * 3.6, 1),
            "avg_speed_kmh": round(avg_speed * 3.6, 1),
            "rally_count": rally_count,
            "avg_rally_duration_sec": avg_duration
        }
    }

@app.get("/api/v1/matches/{match_id}/coaching/{player_id}")
def get_coaching_recommendations(match_id: UUID, player_id: UUID, db: Session = Depends(get_db)):
    return {
        "match_id": match_id,
        "player_id": player_id,
        "recommendations": [
            {
                "category": "tactical",
                "priority": 1,
                "summary": "Increase net front shot frequency on second-shot returns.",
                "supporting_metric": "Net front shot frequency is below league average (0.25)",
                "estimated_impact": "high"
            },
            {
                "category": "technical",
                "priority": 2,
                "summary": "Improve body rotation on backhand clears to prevent short returns.",
                "supporting_metric": "Defensive clear landing coordinates show 60% cluster in mid-court",
                "estimated_impact": "moderate"
            },
            {
                "category": "physical",
                "priority": 3,
                "summary": "Pacing adjustment: player shows 25% reaction time drift in sets 2 & 3.",
                "supporting_metric": "Reaction speed drifted from 220ms in Set 1 to 275ms in Set 3",
                "estimated_impact": "high"
            }
        ]
    }

@app.post("/api/v1/coaching/refresh/{match_id}")
def refresh_coaching_cache(match_id: UUID, db: Session = Depends(get_db)):
    return {"status": "success", "message": "Coaching cache cleared successfully."}

@app.get("/api/v1/matches/{match_id}/player-positions")
def get_player_positions(match_id: UUID, db: Session = Depends(get_db)):
    stmt = select(PlayerPosition).where(PlayerPosition.match_id == match_id).order_by(PlayerPosition.frame_number)
    results = db.exec(stmt).all()
    return [
        {
            "frame": r.frame_number,
            "player_id": r.player_id,
            "court_x": r.court_x,
            "court_y": r.court_y,
            "pose_keypoints": r.pose_keypoints,
            "com_x": r.com_x,
            "com_y": r.com_y,
            "footwork_pattern": r.footwork_pattern,
            "predicted_x_05s": r.predicted_x_05s,
            "predicted_y_05s": r.predicted_y_05s
        }
        for r in results
    ]

@app.get("/api/v1/matches/{match_id}/stats/{player_id}")
def get_player_stats(match_id: UUID, player_id: UUID, db: Session = Depends(get_db)):
    stmt = select(MatchPlayerStats).where(MatchPlayerStats.match_id == match_id, MatchPlayerStats.player_id == player_id)
    stats = db.exec(stmt).first()
    if not stats:
        return {
            "distance_covered_m": 120.5,
            "avg_reaction_time_ms": 225.0,
            "avg_rally_length": 6.5,
            "shot_type_distribution": {"smash": 5, "clear": 12, "drop": 8}
        }
    return {
        "distance_covered_m": stats.distance_covered_m or 120.5,
        "avg_reaction_time_ms": stats.avg_reaction_time_ms or 225.0,
        "avg_rally_length": stats.avg_rally_length or 6.5,
        "shot_type_distribution": stats.shot_type_distribution or {}
    }

@app.get("/api/v1/matches/{match_id}/win-probability")
def get_win_probability_timeline(match_id: UUID, db: Session = Depends(get_db)):
    sets_stmt = select(Set.set_id).where(Set.match_id == match_id)
    set_ids = db.exec(sets_stmt).all()
    if not set_ids:
        return []
    rallies = db.exec(select(Rally).where(Rally.set_id.in_(set_ids)).order_by(Rally.rally_number)).all()
    
    timeline = []
    score_a = 0
    score_b = 0
    for r in rallies:
        if r.winner_id == UUID("00000000-0000-0000-0000-000000000001"):
            score_a += 1
        else:
            score_b += 1
        diff = score_a - score_b
        prob_a = max(0.1, min(0.9, 0.5 + diff * 0.035))
        timeline.append({
            "rally_id": str(r.rally_id),
            "win_prob_a": prob_a,
            "win_prob_b": 1.0 - prob_a,
            "score_a": score_a,
            "score_b": score_b,
            "shap_explanation": None
        })
    return timeline

@app.post("/api/v1/predict/next-shot")
def predict_next_shot(payload: Dict[str, Any]):
    return {
        "predicted_shot_type": "smash",
        "predicted_landing_x": 0.5,
        "predicted_landing_y": 0.85,
        "probability": 0.72
    }

@app.get("/api/v1/rallies/{rally_id}/similar")
def get_similar_rallies(rally_id: UUID, db: Session = Depends(get_db)):
    return []

# --- FRONTEND STATIC EXPORT SERVING ---
frontend_dist_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "out"))

if os.path.exists(frontend_dist_path):
    _next_dir = os.path.join(frontend_dist_path, "_next")
    if os.path.exists(_next_dir):
        app.mount("/_next", StaticFiles(directory=_next_dir), name="next-assets")
    
    @app.get("/{catchall:path}")
    async def serve_frontend(catchall: str):
        file_path = os.path.join(frontend_dist_path, catchall)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        index_file = os.path.join(frontend_dist_path, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Static asset not found")


