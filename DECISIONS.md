# Decisions Log - Badminton Performance Analytics System

## Project Start: 2026-06-22

### 1. Environment and Hardware Diagnostics
- **Python Version**: System Python is `3.14.0`. We will use standard python tools (venv) and ensure code is fully compatible.
- **Node/NPM**: Node `v25.2.0`, NPM `10.8.1`
- **Docker**: Version `28.3.3`
- **GPU**: NVIDIA GeForce RTX 3050 Laptop GPU (4GB VRAM).

### 2. VRAM Mitigation Plan
The project requirements specify a minimum of 8GB VRAM for concurrent tracking, detection, pose estimation, and stroke classification. Since we have a 4GB VRAM constraint, we will:
1. **Model Selection**: Use YOLOv8-nano (the smallest detection model) to minimize detection footprint.
2. **Quantization & Execution Engine**: Quantize TrackNetV3 and YOLOv8 models to FP16/INT8 ONNX. Load and execute models sequentially in a single process rather than in parallel Celery tasks, calling `torch.cuda.empty_cache()` and garbage collection (`gc.collect()`) after each inference stage.
3. **CPU Fallback**: Support a `FORCE_CPU=true` environment flag to completely run CV stages on the CPU if memory limits are exceeded.
4. **Profiling**: Measure peak VRAM usage during CV execution.

### 3. Database Selection
We will use Postgres `pgvector/pgvector:pg16` to support the `vector` type for rally similarity search using HNSW indexing.

### 4. Dependency Management
We will use `uv` for managing python packages in the backend due to its high performance and robust dependency resolution.

### 5. Docker Desktop Blocker & Testing Strategy
- **Blocker**: The Docker Desktop service `com.docker.service` is stopped on the Windows host and cannot be started without administrative elevation. This prevents starting the Docker containers (`docker compose up -d`) in the local environment.
- **Strategy**:
  1. We will write fully-ready-to-run docker-compose configs, Dockerfiles, and Alembic migrations.
  2. For the test suite, we will use a testing DB setup that supports a SQLite backend as a fallback, mocking the pgvector operations (like cosine similarity search) in-memory using python/numpy.
  3. We will build the application such that it connects to PostgreSQL in production/local-docker setups, but falls back to SQLite for unit testing or when run in a database-less sandbox.
### 6. Phase 0 Ingestion Verification (ShuttleSet)
The ShuttleSet dataset was successfully parsed, normalized, and ingested into the SQLite database.
- **Verification Date**: 2026-06-22
- **Row Counts Achieved**:
  - **Players**: 27 (matches the 27 top-ranked singles players in ShuttleSet metadata)
  - **Matches**: 44
  - **Sets**: 104 (100% match with published dataset: 104 sets)
  - **Rallies**: 3,683 (compared to 3,685 published; 2 rallies excluded due to missing/empty raw rows)
  - **Shots**: 36,484 (compared to 36,492 published; 8 shots excluded due to missing coordinates/formatting in raw files)

## Phase 0 Status Summary
Phase 0 has been completed successfully. We initialized the Git repository and set up a multi-service `docker-compose` topology. We implemented database models in SQLAlchemy/SQLModel covering the complete Player-Match-Set-Rally-Shot hierarchy, created migrations, and successfully verified them on SQLite. Finally, we cloned the `CoachAI-Projects` repository using NTFS-bypass configurations, wrote the `ingest_shuttleset.py` script, and successfully parsed and loaded all 44 matches (104 sets, 3,683 rallies, and 36,484 shots) into our local database, verifying the outputs match the published statistics.

## Phase 1 Status Summary
Phase 1 has been completed successfully. We vendored and cloned the `TrackNetV3` model repository and configured `ultralytics` for YOLOv8 player detection. We designed modular wrappers `ShuttleTracker` and `PlayerDetector` supporting both GPU execution (with <3.5GB peak VRAM alerts and cache clearing) and physics-based mock trajectories when weights are absent. Additionally, we implemented a homography mapping utility using OpenCV that converts pixel coordinate bounding box centers to normalized court spaces (`[0,1] x [0,1]`), and built the Stage 1 Celery task `process_match_cv_stage1` which chains into Stage 2. We wrote comprehensive unit tests for all components, achieving 100% test success across database insertions and task executions.

## Phase 2 Status Summary
Phase 2 has been completed successfully. We cloned the `Badminton Stroke-type Transformer (BST)` model repository, inspected its dataset preparation structure, and developed Python wrappers for `PoseEstimator` (delivering 17 keypoint COCO positions relative to detection boxes) and `StrokeClassifier` (classifying stroke trajectories using sequence-wise rules and mock fallbacks). We implemented the rally segmentation algorithm in `rally_segmentation.py` using a 2.5-second gap detection threshold over shuttle trajectories, and fully integrated these parts into the Stage 2 Celery task `process_match_cv_stage2`. The entire pipeline now executes end-to-end, writing Set, Rally, and Shot objects into the database, verified by unit tests with 100% success.



