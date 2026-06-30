import os
os.environ["DATABASE_URL"] = "sqlite://"

from uuid import uuid4
from sqlmodel import Session, select
from src.pipeline.database import engine, init_db
from src.pipeline.models import Player, Match, ShuttleTrajectory
from src.pipeline.video_processor import process_video_and_sync

def test_database_and_models():
    # Initialize in-memory DB tables
    init_db()
    
    with Session(engine) as session:
        # Create players
        p1 = Player(name="Viktor Axelsen", handedness="right", country="Denmark")
        p2 = Player(name="Lee Zii Jia", handedness="right", country="Malaysia")
        session.add(p1)
        session.add(p2)
        session.commit()
        session.refresh(p1)
        session.refresh(p2)
        
        assert p1.name == "Viktor Axelsen"
        assert p2.name == "Lee Zii Jia"

        # Create Match
        m = Match(
            player_a_id=p1.player_id,
            player_b_id=p2.player_id,
            tournament="All England Open 2026",
            source_type="broadcast",
            processing_status="pending"
        )
        session.add(m)
        session.commit()
        session.refresh(m)
        
        assert m.tournament == "All England Open 2026"
        assert m.processing_status == "pending"

def test_video_processing_pipeline():
    with Session(engine) as session:
        m = session.exec(select(Match)).first()
        
        # Test progress generator
        generator = process_video_and_sync(m.match_id, "dummy.mp4")
        updates = list(generator)
        
        assert len(updates) > 0
        assert updates[-1]["status"] == "done"
        
        # Check processing completed
        session.refresh(m)
        assert m.processing_status == "done"

def test_tracknet_pipeline(tmp_path):
    # 1. Create a folder of mock images
    image_dir = tmp_path / "mock_frames"
    image_dir.mkdir()
    
    import numpy as np
    import cv2
    
    # Write 5 mock images (black frames)
    for i in range(5):
        img_path = image_dir / f"{i:04d}.jpg"
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.imwrite(str(img_path), img)
        
    video_path = tmp_path / "mock_video.mp4"
    
    # 2. Test images_to_video
    from src.pipeline.images_to_video import images_to_video
    images_to_video(str(image_dir), str(video_path), fps=30)
    assert video_path.exists()
    
    # 3. Test track_video
    from src.pipeline.track_ball import track_video
    output_video_path = tmp_path / "tracked_video.mp4"
    ball_track = track_video(str(video_path), str(output_video_path), "model_best.pt", extrapolate=True)
    
    assert output_video_path.exists()
    assert len(ball_track) == 5
