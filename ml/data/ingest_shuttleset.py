import os
import re
import ast
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from shared.models import Player, Match, Set, Rally, Shot
from shared.database import DATABASE_URL

# Set up DB session
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Mapping Chinese shot types to English (18-class taxonomy guidelines)
SHOT_TYPE_MAP = {
    '發短球': 'short serve',
    '發長球': 'long/flick serve',
    '放小球': 'net shot',
    '勾球': 'net shot',
    '撲球': 'push/net kill',
    '推球': 'drive', # or push
    '挑球': 'lift',
    '防守回挑': 'lift',
    '長球': 'defensive clear',
    '切球': 'drop shot',
    '過度切球': 'slice/cut drop',
    '平球': 'drive',
    '後場抽平球': 'drive',
    '防守回抽': 'drive',
    '殺球': 'smash',
    '點扣': 'wrist smash',
    '擋小球': 'block',
    '未知球種': 'unclassified / unknown'
}

def clean_name(name: str) -> str:
    """Clean player names for consistency."""
    if not isinstance(name, str):
        return "Unknown"
    # Convert uppercase names or spaces
    return name.strip()

def get_or_create_player(session, name: str) -> Player:
    """Get player or create new one if not exists."""
    cleaned = clean_name(name)
    player = session.query(Player).filter(Player.name == cleaned).first()
    if not player:
        # Detect handedness if known, default to right
        handedness = "right"
        player = Player(name=cleaned, handedness=handedness)
        session.add(player)
        session.commit()
        session.refresh(player)
    return player

def parse_homography_matrix(matrix_str: str) -> np.ndarray:
    """Safely parse homography matrix from string."""
    try:
        # Standardize matrix string formatting
        cleaned_str = matrix_str.replace('\n', '').replace(' ', ',')
        cleaned_str = re.sub(r',+', ',', cleaned_str)
        cleaned_str = cleaned_str.replace('[,', '[').replace(',]', ']')
        return np.array(ast.literal_eval(cleaned_str))
    except Exception as e:
        print(f"Error parsing homography matrix: {e} for {matrix_str}")
        return np.eye(3)

def apply_homography(x, y, matrix) -> tuple:
    """Apply homography matrix to pixel coordinates."""
    if pd.isna(x) or pd.isna(y):
        return None, None
    try:
        p = np.array([float(x), float(y), 1.0])
        p_real = matrix.dot(p)
        if p_real[2] != 0:
            p_real /= p_real[2]
            return float(p_real[0]), float(p_real[1])
    except Exception:
        pass
    return None, None

def normalize_court_coords(x, y) -> tuple:
    """Normalize court coordinates to [0,1] x [0,1]."""
    if x is None or y is None:
        return None, None
    # Court size in real-world pixels/dimensions (based on ShuttleSet calibration):
    # Length: ~13.4m, Width: ~6.1m
    # x ranges roughly from 0 to 350, y from 0 to 960 in real coords
    # Normalize to [0,1]
    norm_x = clip(x / 355.0)
    norm_y = clip(y / 960.0)
    return norm_x, norm_y

def clip(val, min_val=0.0, max_val=1.0):
    return max(min_val, min(max_val, val))

def ingest_shuttleset(data_dir: str):
    SQLModel.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:

        print("Starting ShuttleSet Ingestion...")
        match_csv_path = os.path.join(data_dir, "set", "match.csv")
        homography_csv_path = os.path.join(data_dir, "set", "homography.csv")

        if not os.path.exists(match_csv_path) or not os.path.exists(homography_csv_path):
            print(f"Dataset path {match_csv_path} not found!")
            return

        matches_df = pd.read_csv(match_csv_path)
        homography_df = pd.read_csv(homography_csv_path)

        # Parse homography matrices into dictionary
        homography_map = {}
        for _, row in homography_df.iterrows():
            video_name = row['video']
            matrix_str = row['homography_matrix']
            homography_map[video_name] = parse_homography_matrix(matrix_str)

        # Process each match
        for idx, row in matches_df.iterrows():
            match_id = row['id']
            video_name = row['video']
            tournament = row['tournament']
            winner_name = row['winner']
            loser_name = row['loser']
            
            # Match date parsing
            try:
                match_date = pd.to_datetime(f"{row['year']}-{row['month']}-{row['day']}").date()
            except Exception:
                match_date = None

            print(f"Ingesting match: {video_name} ({tournament})")

            # Get or create players
            player_a = get_or_create_player(session, winner_name)
            player_b = get_or_create_player(session, loser_name)

            # Create Match
            match = Match(
                tournament=tournament,
                match_date=match_date,
                video_uri=f"s3://badminton-videos/{video_name}.mp4",
                source_type="broadcast",
                fps=30.0,
                processing_status="done",
                player_a_id=player_a.player_id,
                player_b_id=player_b.player_id
            )
            # Add court calibration homography to Match row
            h_matrix = homography_map.get(video_name, np.eye(3))
            match.court_calibration = {"homography_matrix": h_matrix.tolist()}
            session.add(match)
            session.commit()
            session.refresh(match)

            # Locate set CSV files
            match_dir = os.path.join(data_dir, "set", video_name)
            if not os.path.exists(match_dir):
                print(f"Warning: Set directory {match_dir} does not exist!")
                continue

            csv_files = [f for f in os.listdir(match_dir) if f.endswith('.csv')]
            for csv_file in csv_files:
                set_num_match = re.search(r'\d+', csv_file)
                if not set_num_match:
                    continue
                set_num = int(set_num_match.group())
                
                # Create Set
                # Default score to 21-19 if not in CSV metadata
                score_a = 21 if row['winner'] == winner_name else 19
                score_b = 19 if row['winner'] == winner_name else 21
                match_set = Set(
                    match_id=match.match_id,
                    set_number=set_num,
                    score_a=score_a,
                    score_b=score_b,
                    winner_id=player_a.player_id
                )
                session.add(match_set)
                session.commit()
                session.refresh(match_set)

                # Read Set CSV
                set_df = pd.read_csv(os.path.join(match_dir, csv_file))
                
                # Group strokes by rally
                rallies_group = set_df.groupby('rally')
                for rally_num, group in rallies_group:
                    # Get server for the rally (from first stroke in rally)
                    first_row = group.iloc[0]
                    server_label = first_row['server']
                    server_player = player_a if server_label == 1 else player_b
                    
                    # Last row contains winner details
                    last_row = group.iloc[-1]
                    point_winner_label = last_row.get('getpoint_player')
                    winner_player = None
                    if point_winner_label == 'A':
                        winner_player = player_a
                    elif point_winner_label == 'B':
                        winner_player = player_b
                    else:
                        # Fallback to match winner
                        winner_player = player_a

                    # End reason mapping
                    end_reason = "winner"
                    lose_reason_val = last_row.get('lose_reason')
                    if pd.notna(lose_reason_val):
                        if '出界' in str(lose_reason_val) or '掛網' in str(lose_reason_val):
                            end_reason = "unforced_error"
                        elif '防守' in str(lose_reason_val):
                            end_reason = "forced_error"
                    
                    # Start / end time estimation
                    start_frame = int(first_row['frame_num']) if pd.notna(first_row['frame_num']) else 0
                    end_frame = int(last_row['frame_num']) if pd.notna(last_row['frame_num']) else 0
                    start_ts_ms = start_frame * 33 # roughly 30 fps
                    end_ts_ms = end_frame * 33

                    # Create Rally
                    rally = Rally(
                        set_id=match_set.set_id,
                        rally_number=int(rally_num),
                        server_id=server_player.player_id,
                        winner_id=winner_player.player_id if winner_player else None,
                        rally_length=len(group),
                        start_frame=start_frame,
                        end_frame=end_frame,
                        start_ts_ms=start_ts_ms,
                        end_ts_ms=end_ts_ms,
                        end_reason=end_reason
                    )
                    session.add(rally)
                    session.commit()
                    session.refresh(rally)

                    # Create Shots
                    for shot_idx, (_, shot_row) in enumerate(group.iterrows(), start=1):
                        hitter_label = shot_row['player']
                        hitter = player_a if hitter_label == 'A' else player_b
                        
                        raw_type = shot_row['type']
                        shot_type = SHOT_TYPE_MAP.get(raw_type, 'unclassified / unknown')

                        # Apply homography
                        hit_x_px, hit_y_px = shot_row.get('hit_x'), shot_row.get('hit_y')
                        landing_x_px, landing_y_px = shot_row.get('landing_x'), shot_row.get('landing_y')
                        loc_x_px, loc_y_px = shot_row.get('player_location_x'), shot_row.get('player_location_y')
                        opp_x_px, opp_y_px = shot_row.get('opponent_location_x'), shot_row.get('opponent_location_y')

                        # Map and transform positions using homography matrix
                        hitter_x, hitter_y = apply_homography(loc_x_px, loc_y_px, h_matrix)
                        receiver_x, receiver_y = apply_homography(opp_x_px, opp_y_px, h_matrix)
                        landing_x, landing_y = apply_homography(landing_x_px, landing_y_px, h_matrix)

                        # Normalize coordinates
                        norm_hitter_x, norm_hitter_y = normalize_court_coords(hitter_x, hitter_y)
                        norm_receiver_x, norm_receiver_y = normalize_court_coords(receiver_x, receiver_y)
                        norm_landing_x, norm_landing_y = normalize_court_coords(landing_x, landing_y)

                        hit_frame = int(shot_row['frame_num']) if pd.notna(shot_row['frame_num']) else 0
                        hit_ts_ms = hit_frame * 33

                        # Determine if shot is a winner / error
                        is_winner = False
                        is_error = False
                        if shot_idx == len(group):
                            if end_reason == "winner" and winner_player == hitter:
                                is_winner = True
                            elif end_reason in ["unforced_error", "fault"] and winner_player != hitter:
                                is_error = True

                        shot = Shot(
                            rally_id=rally.rally_id,
                            shot_number=shot_idx,
                            hitter_id=hitter.player_id,
                            shot_type=shot_type,
                            hit_frame=hit_frame,
                            hit_ts_ms=hit_ts_ms,
                            hitter_court_x=norm_hitter_x,
                            hitter_court_y=norm_hitter_y,
                            receiver_court_x=norm_receiver_x,
                            receiver_court_y=norm_receiver_y,
                            landing_x=norm_landing_x,
                            landing_y=norm_landing_y,
                            shuttle_speed_est=15.0, # default placeholder speed
                            confidence=1.0,
                            is_winner=is_winner,
                            is_error=is_error
                        )
                        session.add(shot)
                    session.commit()

        print("ShuttleSet Ingestion Completed Successfully!")
    except Exception as e:
        session.rollback()
        print(f"Error during ingestion: {e}")
        raise e
    finally:
        session.close()

if __name__ == "__main__":
    # Base dataset path
    data_dir = "ml/data/raw/CoachAI-Projects/ShuttleSet"
    ingest_shuttleset(data_dir)
