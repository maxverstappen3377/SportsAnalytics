import pytest
from uuid import uuid4
from datetime import date
from sqlmodel import SQLModel, create_engine, Session
from shared.models import Player, Match, Set, Rally, Shot, ShuttleTrajectory, PlayerPosition, MatchPlayerStats, RallyEmbedding

# Use in-memory SQLite for testing database schemas
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="db_session")
def db_session_fixture():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

def test_db_schema_and_cascade(db_session: Session):
    # 1. Create players
    player_a = Player(name="Viktor Axelsen", handedness="right", country="Denmark")
    player_b = Player(name="Lee Zii Jia", handedness="right", country="Malaysia")
    db_session.add(player_a)
    db_session.add(player_b)
    db_session.commit()
    db_session.refresh(player_a)
    db_session.refresh(player_b)

    assert player_a.player_id is not None
    assert player_b.player_id is not None
    assert player_a.name == "Viktor Axelsen"

    # 2. Create Match
    match = Match(
        player_a_id=player_a.player_id,
        player_b_id=player_b.player_id,
        tournament="All England Open",
        match_date=date(2024, 3, 15),
        source_type="broadcast",
        fps=30.0,
        processing_status="pending"
    )
    db_session.add(match)
    db_session.commit()
    db_session.refresh(match)
    assert match.match_id is not None

    # 3. Create Set
    match_set = Set(
        match_id=match.match_id,
        set_number=1,
        score_a=21,
        score_b=19,
        winner_id=player_a.player_id
    )
    db_session.add(match_set)
    db_session.commit()
    db_session.refresh(match_set)
    assert match_set.set_id is not None

    # 4. Create Rally
    rally = Rally(
        set_id=match_set.set_id,
        rally_number=1,
        server_id=player_a.player_id,
        winner_id=player_a.player_id,
        rally_length=3,
        start_frame=100,
        end_frame=300,
        start_ts_ms=3333,
        end_ts_ms=10000,
        end_reason="winner"
    )
    db_session.add(rally)
    db_session.commit()
    db_session.refresh(rally)
    assert rally.rally_id is not None

    # 5. Create Shots
    shot_1 = Shot(
        rally_id=rally.rally_id,
        shot_number=1,
        hitter_id=player_a.player_id,
        shot_type="serve low",
        hit_frame=100,
        hit_ts_ms=3333,
        hitter_court_x=0.5,
        hitter_court_y=0.25,
        receiver_court_x=0.5,
        receiver_court_y=0.75,
        landing_x=0.5,
        landing_y=0.6,
        confidence=0.99
    )
    shot_2 = Shot(
        rally_id=rally.rally_id,
        shot_number=2,
        hitter_id=player_b.player_id,
        shot_type="push/net kill",
        hit_frame=180,
        hit_ts_ms=6000,
        hitter_court_x=0.5,
        hitter_court_y=0.6,
        receiver_court_x=0.5,
        receiver_court_y=0.25,
        landing_x=0.2,
        landing_y=0.1,
        confidence=0.95
    )
    db_session.add(shot_1)
    db_session.add(shot_2)
    db_session.commit()
    db_session.refresh(shot_1)
    db_session.refresh(shot_2)
    assert shot_1.shot_id is not None
    assert shot_2.shot_id is not None

    # 6. Verify cascading reads
    loaded_rally = db_session.query(Rally).filter(Rally.rally_id == rally.rally_id).first()
    assert loaded_rally is not None
    
    # Load shots for this rally
    loaded_shots = db_session.query(Shot).filter(Shot.rally_id == loaded_rally.rally_id).order_by(Shot.shot_number).all()
    assert len(loaded_shots) == 2
    assert loaded_shots[0].shot_type == "serve low"
    assert loaded_shots[1].shot_type == "push/net kill"
