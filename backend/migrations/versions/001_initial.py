"""initial migration

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-22 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Enable extensions (check if postgres dialet before running)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Players table
    op.create_table(
        'players',
        sa.Column('player_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('handedness', sa.String(), nullable=True),
        sa.Column('country', sa.String(), nullable=True),
        sa.Column('external_ref', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('player_id'),
        sa.CheckConstraint("handedness IN ('left', 'right')", name='check_handedness')
    )

    # Matches table
    op.create_table(
        'matches',
        sa.Column('match_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('player_a_id', sa.UUID(), nullable=True),
        sa.Column('player_b_id', sa.UUID(), nullable=True),
        sa.Column('tournament', sa.String(), nullable=True),
        sa.Column('match_date', sa.Date(), nullable=True),
        sa.Column('video_uri', sa.String(), nullable=True),
        sa.Column('court_calibration', sa.JSON(), nullable=True),
        sa.Column('source_type', sa.String(), nullable=True),
        sa.Column('fps', sa.Numeric(), nullable=True),
        sa.Column('processing_status', sa.String(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['player_a_id'], ['players.player_id'], ),
        sa.ForeignKeyConstraint(['player_b_id'], ['players.player_id'], ),
        sa.PrimaryKeyConstraint('match_id'),
        sa.CheckConstraint("source_type IN ('broadcast', 'courtside', 'training')", name='check_source_type'),
        sa.CheckConstraint("processing_status IN ('pending','queued','processing_cv','processing_analytics','done','failed')", name='check_processing_status')
    )

    # Sets table
    op.create_table(
        'sets',
        sa.Column('set_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('match_id', sa.UUID(), nullable=False),
        sa.Column('set_number', sa.Integer(), nullable=False),
        sa.Column('score_a', sa.Integer(), nullable=True),
        sa.Column('score_b', sa.Integer(), nullable=True),
        sa.Column('winner_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['match_id'], ['matches.match_id'], ),
        sa.ForeignKeyConstraint(['winner_id'], ['players.player_id'], ),
        sa.PrimaryKeyConstraint('set_id')
    )

    # Rallies table
    op.create_table(
        'rallies',
        sa.Column('rally_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('set_id', sa.UUID(), nullable=False),
        sa.Column('rally_number', sa.Integer(), nullable=False),
        sa.Column('server_id', sa.UUID(), nullable=True),
        sa.Column('winner_id', sa.UUID(), nullable=True),
        sa.Column('rally_length', sa.Integer(), nullable=True),
        sa.Column('start_frame', sa.Integer(), nullable=True),
        sa.Column('end_frame', sa.Integer(), nullable=True),
        sa.Column('start_ts_ms', sa.Numeric(20, 0), nullable=True),
        sa.Column('end_ts_ms', sa.Numeric(20, 0), nullable=True),
        sa.Column('end_reason', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['set_id'], ['sets.set_id'], ),
        sa.ForeignKeyConstraint(['server_id'], ['players.player_id'], ),
        sa.ForeignKeyConstraint(['winner_id'], ['players.player_id'], ),
        sa.PrimaryKeyConstraint('rally_id'),
        sa.CheckConstraint("end_reason IN ('winner', 'unforced_error', 'forced_error', 'fault')", name='check_end_reason')
    )

    # Shots table
    op.create_table(
        'shots',
        sa.Column('shot_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('rally_id', sa.UUID(), nullable=False),
        sa.Column('shot_number', sa.Integer(), nullable=False),
        sa.Column('hitter_id', sa.UUID(), nullable=True),
        sa.Column('shot_type', sa.String(), nullable=False),
        sa.Column('hit_frame', sa.Integer(), nullable=True),
        sa.Column('hit_ts_ms', sa.Numeric(20, 0), nullable=True),
        sa.Column('hitter_court_x', sa.Numeric(5, 4), nullable=True),
        sa.Column('hitter_court_y', sa.Numeric(5, 4), nullable=True),
        sa.Column('receiver_court_x', sa.Numeric(5, 4), nullable=True),
        sa.Column('receiver_court_y', sa.Numeric(5, 4), nullable=True),
        sa.Column('landing_x', sa.Numeric(5, 4), nullable=True),
        sa.Column('landing_y', sa.Numeric(5, 4), nullable=True),
        sa.Column('shuttle_speed_est', sa.Numeric(6, 2), nullable=True),
        sa.Column('confidence', sa.Numeric(4, 3), nullable=True),
        sa.Column('is_winner', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_error', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.ForeignKeyConstraint(['hitter_id'], ['players.player_id'], ),
        sa.ForeignKeyConstraint(['rally_id'], ['rallies.rally_id'], ),
        sa.PrimaryKeyConstraint('shot_id')
    )

    # Shuttle Trajectory table
    op.create_table(
        'shuttle_trajectory',
        sa.Column('match_id', sa.UUID(), nullable=False),
        sa.Column('frame_number', sa.Integer(), nullable=False),
        sa.Column('pixel_x', sa.Numeric(8, 2), nullable=True),
        sa.Column('pixel_y', sa.Numeric(8, 2), nullable=True),
        sa.Column('court_x', sa.Numeric(5, 4), nullable=True),
        sa.Column('court_y', sa.Numeric(5, 4), nullable=True),
        sa.Column('visible', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.ForeignKeyConstraint(['match_id'], ['matches.match_id'], ),
        sa.PrimaryKeyConstraint('match_id', 'frame_number')
    )

    # Player Positions table
    op.create_table(
        'player_positions',
        sa.Column('match_id', sa.UUID(), nullable=False),
        sa.Column('frame_number', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.UUID(), nullable=False),
        sa.Column('court_x', sa.Numeric(5, 4), nullable=True),
        sa.Column('court_y', sa.Numeric(5, 4), nullable=True),
        sa.Column('pose_keypoints', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['match_id'], ['matches.match_id'], ),
        sa.ForeignKeyConstraint(['player_id'], ['players.player_id'], ),
        sa.PrimaryKeyConstraint('match_id', 'frame_number', 'player_id')
    )

    # Match Player Stats table
    op.create_table(
        'match_player_stats',
        sa.Column('match_id', sa.UUID(), nullable=False),
        sa.Column('player_id', sa.UUID(), nullable=False),
        sa.Column('distance_covered_m', sa.Numeric(8, 2), nullable=True),
        sa.Column('avg_reaction_time_ms', sa.Numeric(8, 2), nullable=True),
        sa.Column('shot_type_distribution', sa.JSON(), nullable=True),
        sa.Column('win_rate_by_rally_length', sa.JSON(), nullable=True),
        sa.Column('avg_rally_length', sa.Numeric(5, 2), nullable=True),
        sa.Column('pressure_index', sa.Numeric(4, 3), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['match_id'], ['matches.match_id'], ),
        sa.ForeignKeyConstraint(['player_id'], ['players.player_id'], ),
        sa.PrimaryKeyConstraint('match_id', 'player_id')
    )

    # Rally Embeddings table
    if bind.dialect.name == "postgresql":
        op.create_table(
            'rally_embeddings',
            sa.Column('rally_id', sa.UUID(), nullable=False),
            sa.Column('embedding', Vector(256), nullable=False),
            sa.ForeignKeyConstraint(['rally_id'], ['rallies.rally_id'], ),
            sa.PrimaryKeyConstraint('rally_id')
        )
        # Create HNSW index
        op.execute("CREATE INDEX rally_embeddings_hnsw ON rally_embeddings USING hnsw (embedding vector_cosine_ops)")
    else:
        # SQLite fallback: store embedding as JSON/Text or skip
        op.create_table(
            'rally_embeddings',
            sa.Column('rally_id', sa.UUID(), nullable=False),
            sa.Column('embedding', sa.TEXT(), nullable=False),
            sa.ForeignKeyConstraint(['rally_id'], ['rallies.rally_id'], ),
            sa.PrimaryKeyConstraint('rally_id')
        )

    # Secondary indexes
    op.create_index('idx_shots_rally', 'shots', ['rally_id'])
    op.create_index('idx_shots_hitter', 'shots', ['hitter_id'])
    op.create_index('idx_rallies_set', 'rallies', ['set_id'])
    op.create_index('idx_matches_status', 'matches', ['processing_status'])

def downgrade() -> None:
    op.drop_index('idx_matches_status')
    op.drop_index('idx_rallies_set')
    op.drop_index('idx_shots_hitter')
    op.drop_index('idx_shots_rally')
    
    op.drop_table('rally_embeddings')
    op.drop_table('match_player_stats')
    op.drop_table('player_positions')
    op.drop_table('shuttle_trajectory')
    op.drop_table('shots')
    op.drop_table('rallies')
    op.drop_table('sets')
    op.drop_table('matches')
    op.drop_table('players')
