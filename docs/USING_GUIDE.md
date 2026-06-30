# Using Guide - Badminton Performance Analytics System

Welcome to the **Badminton Performance Analytics System**! This document provides detailed, step-by-step instructions on setting up, running, using, and troubleshooting the entire analytics application.

---

## 1. System Overview

This platform maps raw badminton match videos into high-fidelity descriptive, predictive, and prescriptive insights:

```
[Raw Video Upload] -> [CV Worker tracking, pose, strokes] -> [Analytics Descriptive Stats]
                                                                    |
                                                                    v
[Structured Advice] <- [Prescriptive LLM Rules/Coach] <- [Predictive ML (XGBoost/LSTM)]
```

- **Descriptive Layer**: Calculates hit/landing heatmaps, distance covered, reaction time drift, shot type distributions, and return-of-serve patterns.
- **Predictive Layer**: Provides live match set win-probabilities (XGBoost) and predicts the next shot type (PyTorch LSTM).
- **Prescriptive Layer**: Uses rule engines and Claude-3.5 to deliver tactical coaching tips categorized by tactical, technical, and physical fields.

---

## 2. Quick Start (Local Setup)

Follow these steps to run the application locally on your host machine without Docker.

### Step 2.1: Database Seeding
The backend contains a SQLite fallback mode suitable for testing and local sandbox execution. Seed the database with official ShuttleSet matches:
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate       # Windows
# Install dependencies
pip install -r pyproject.toml
# Run seed script
python ml/data/ingest_shuttleset.py
```
This extracts annotated matches, sets, rallies, and shots into `badminton-analytics/badminton.db`.

### Step 2.2: Running the Services
To start the descriptive, predictive, and prescriptive APIs, spin up three separate terminals:

**Terminal 1: Ingestion Service (:8001)**
```bash
cd backend
.venv\Scripts\activate
python ingest_svc/main.py
```

**Terminal 2: Analytics Service (:8002)**
```bash
cd backend
.venv\Scripts\activate
python analytics_svc/main.py
```

**Terminal 3: Coaching Service (:8003)**
```bash
cd backend
.venv\Scripts\activate
python coach_svc/main.py
```

### Step 2.3: Starting the Celery CV Worker
The background computer vision task pipeline runs via Celery. In a fourth terminal:
```bash
cd backend
.venv\Scripts\activate
# Start Celery worker using the solo pool (recommended for Windows/CPU fallback)
celery -A cv_worker.tasks worker --loglevel=info -P solo
```

### Step 2.4: Launching the Next.js Frontend (:3000)
To launch the user interface:
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:3000` in your web browser.

---

## 3. Production Deployment (Docker)

To deploy the fully integrated production stack with PostgreSQL + pgvector, Redis, MinIO S3, and Next.js:
```bash
docker compose -f docker-compose.prod.yml up --build -d
```
All environment variables (including database URIs, Redis broker ports, and fallback modes) are pre-configured out-of-the-box.

---

## 4. End-to-End User Workflow

Follow this sequence to ingest a video and inspect analytics in the dashboard:

### Step 4.1: Authentication
All API routes are protected. Obtain a JWT token by logging in:
- **Endpoint**: `POST /api/v1/auth/login`
- **Request Body**:
  ```json
  {"username": "coach", "password": "coach"}
  ```
- **Response**: Returns an `access_token` JWT. Copy this token and include it in the request headers: `Authorization: Bearer <token>`.

### Step 4.2: Match Registration & Video Upload
1. Register a match metadata record:
   - **Endpoint**: `POST /api/v1/matches`
   - **Request Headers**: `Authorization: Bearer <token>`
   - **Request Body**:
     ```json
     {
       "player_a_id": "player_a_uuid",
       "player_b_id": "player_b_uuid",
       "tournament": "Thomas Cup 2026",
       "source_type": "broadcast"
     }
     ```
   - **Response**: Returns a match JSON containing a pre-signed MinIO S3 upload URL.
2. Upload your raw MP4 video file to the pre-signed S3 URL using an HTTP `PUT` request.

### Step 4.3: Trigger CV Pipeline
Confirm the upload is complete to start background processing:
- **Endpoint**: `POST /api/v1/matches/{match_id}/video/confirm`
- **Response**: Returns status `"queued"`.

This triggers a two-stage asynchronous Celery flow:
1. **Stage 1**: TrackNetV3 tracks shuttle coordinates; YOLOv8 detects player boxes; OpenCV homography maps court boundaries.
2. **Stage 2**: Pose keypoints (MMPose) and stroke classification (BST) segment the rallies and write descriptive stats to the database.

### Step 4.4: Inspect Dashboard Insights
Once the match status is `"done"`, open the Next.js frontend to visualize the following views:
- **Court Heatmap**: Toggle between landing/hitting point density grids (20x10 matrix).
- **Rally Timeline Scrubber**: Track shot-by-shot velocity, position, and stroke types synchronized with video time.
- **Predictive Win Probability**: Interactive line chart plotting set and point margins.
- **Coaching Feed**: View AI-generated recommendations categorized by priority and supporting physical metrics.

---

## 5. Troubleshooting & Diagnostics

- **GPU Memory Errors**: If the CV worker crashes with VRAM limitations, ensure `FORCE_CPU=true` is set in your `.env` file to trigger sequential CPU-based fallback mode.
- **Mock Anthropic Caching**: The coach service caches Anthropic API responses. To clear the LLM cache and fetch a fresh description:
  - **Endpoint**: `POST /api/v1/coaching/refresh/{match_id}`
- **Database Index Status**: Queries are optimized using secondary indexes. Check query plans using:
  ```sql
  EXPLAIN QUERY PLAN SELECT * FROM shots WHERE rally_id = 'your-rally-uuid';
  ```
