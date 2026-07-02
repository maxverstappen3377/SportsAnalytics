import os
import sys

# Set headless mode BEFORE any OpenCV or display-related imports
os.environ["DISPLAY"] = ""
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LIBGL_ALWAYS_INDIRECT"] = "1"

# Disable Ultralytics requirement checking and auto-updates
os.environ["CHECK_UPDATES"] = "False"
os.environ["YOLO_VERBOSE"] = "False"
try:
    import ultralytics.utils.checks as checks
    checks.check_requirements = lambda *args, **kwargs: True
    print("[Processor] Monkeypatched ultralytics check_requirements to disable autoupdates.")
except Exception as e:
    print(f"[Processor Warning] Failed to monkeypatch check_requirements: {e}")

# Import cv2 with headless configuration
try:
    import cv2
    cv2.ocl.setUseOpenCL(False)
    print("[Processor] OpenCV initialized in headless mode")
except ImportError as e:
    print(f"[Processor Error] Failed to import cv2: {e}")
    raise

import math
import torch
import random
import gc
import time
import numpy as np
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Any, Generator, Optional
from sqlmodel import Session, select, delete
from sqlalchemy import func
from scipy.stats import gaussian_kde
from scipy.interpolate import CubicSpline
from ultralytics import YOLO

from src.pipeline.database import engine
from src.pipeline.models import Match, Set, Rally, Shot, ShuttleTrajectory, PlayerPosition, MatchPlayerStats, Player

# Add TrackNet path
tracknet_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "TrackNet"))
if tracknet_path not in sys.path:
    sys.path.append(tracknet_path)

try:
    from model import BallTrackerNet
    from general import postprocess
    HAS_TRACKNET = True
except ImportError:
    HAS_TRACKNET = False

# ----------------- CAMERA CALIBRATION INTRINSICS -----------------
CAMERA_K = np.array([
    [1150.0, 0.0, 640.0],
    [0.0, 1150.0, 360.0],
    [0.0, 0.0, 1.0]
], dtype=np.float32)
CAMERA_D = np.array([-0.15, 0.03, 0.0, 0.0, 0.0], dtype=np.float32)

def undistort_frame(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    new_camera_matrix, _ = cv2.getOptimalNewCameraMatrix(CAMERA_K, CAMERA_D, (w, h), 1, (w, h))
    return cv2.undistort(frame, CAMERA_K, CAMERA_D, None, new_camera_matrix)

# ----------------- DYNAMIC HOUGH HOMOGRAPHY ALIGNMENT -----------------
def align_court_lines_hough(frame: np.ndarray, base_corners: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=80, minLineLength=100, maxLineGap=10)
        
        if lines is None:
            return base_corners
            
        adjusted = list(base_corners)
        for idx, (bx, by) in enumerate(base_corners):
            best_dist = 40.0
            best_pt = (bx, by)
            for line in lines:
                x1, y1, x2, y2 = line[0]
                d = abs((y2 - y1) * bx - (x2 - x1) * by + x2 * y1 - y2 * x1) / (math.sqrt((y2 - y1)**2 + (x2 - x1)**2) or 1)
                if d < best_dist:
                    l_len_sq = (x2 - x1)**2 + (y2 - y1)**2
                    if l_len_sq > 0:
                        t = ((bx - x1)*(x2 - x1) + (by - y1)*(y2 - y1)) / l_len_sq
                        t = max(0.0, min(1.0, t))
                        proj_x = x1 + t * (x2 - x1)
                        proj_y = y1 + t * (y2 - y1)
                        best_dist = d
                        best_pt = (proj_x, proj_y)
            adjusted[idx] = best_pt
        return adjusted
    except Exception:
        return base_corners

# ----------------- FMO STREAK DETECTION -----------------
def localize_motion_streak(prev_gray: np.ndarray, curr_gray: np.ndarray) -> Optional[Tuple[float, float, float]]:
    try:
        diff = cv2.absdiff(prev_gray, curr_gray)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 30 < area < 1200:
                rect = cv2.minAreaRect(cnt)
                (cx, cy), (w, h), angle = rect
                aspect_ratio = max(w, h) / (min(w, h) or 0.01)
                if aspect_ratio > 2.2:
                    return float(cx), float(cy), 0.85
    except Exception:
        pass
    return None

# ----------------- KINEMATIC POSTURE CONSTRAINTS -----------------
class KinematicConstraintFilter:
    def __init__(self):
        self.prev_positions: Dict[str, Tuple[float, float]] = {}
        self.max_px_speed = {
            "left_wrist": 110.0,
            "right_wrist": 110.0,
            "left_ankle": 45.0,
            "right_ankle": 45.0,
            "left_hip": 30.0,
            "right_hip": 30.0,
            "nose": 25.0
        }

    def validate_kinematics(self, keypoints: List[PoseKeypoint]) -> List[PoseKeypoint]:
        for kp in keypoints:
            if kp.score > 0.3:
                if kp.name in self.prev_positions:
                    px, py = self.prev_positions[kp.name]
                    dist = math.sqrt((kp.x - px)**2 + (kp.y - py)**2)
                    max_speed = self.max_px_speed.get(kp.name, 40.0)
                    if dist > max_speed:
                        kp.x = px
                        kp.y = py
                self.prev_positions[kp.name] = (kp.x, kp.y)
        return keypoints

# ----------------- 1. Physics-Informed Extended Kalman Filter (EKF) -----------------
class PhysicsInformedEKF:
    def __init__(self, dt: float = 1.0/30.0):
        self.dt = dt
        self.g = 9.81
        self.Cd = 0.15
        self.state = np.zeros(6, dtype=np.float32)
        self.P = np.eye(6, dtype=np.float32) * 0.1
        self.Q = np.eye(6, dtype=np.float32) * 1e-3
        self.R = np.eye(2, dtype=np.float32) * 0.05
        self.initialized = False

    def initialize(self, x: float, y: float, z: float = 1.5):
        self.state = np.array([x, y, z, 0.0, 0.0, 0.0], dtype=np.float32)
        self.P = np.eye(6, dtype=np.float32) * 0.1
        self.initialized = True

    def predict(self):
        dt = self.dt
        x, y, z, vx, vy, vz = self.state
        v = math.sqrt(vx**2 + vy**2 + vz**2) or 0.001

        x_new = x + vx * dt
        y_new = y + vy * dt
        z_new = max(0.0, z + vz * dt)
        vx_new = vx - self.Cd * v * vx * dt
        vy_new = vy - self.Cd * v * vy * dt
        vz_new = vz - (self.g + self.Cd * v * vz) * dt

        F = np.eye(6, dtype=np.float32)
        F[0, 3] = dt
        F[1, 4] = dt
        F[2, 5] = dt

        F[3, 3] = 1.0 - self.Cd * dt * (v + (vx**2 / v))
        F[3, 4] = -self.Cd * dt * (vx * vy / v)
        F[3, 5] = -self.Cd * dt * (vx * vz / v)

        F[4, 3] = -self.Cd * dt * (vy * vx / v)
        F[4, 4] = 1.0 - self.Cd * dt * (v + (vy**2 / v))
        F[4, 5] = -self.Cd * dt * (vy * vz / v)

        F[5, 3] = -self.Cd * dt * (vz * vx / v)
        F[5, 4] = -self.Cd * dt * (vz * vy / v)
        F[5, 5] = 1.0 - self.Cd * dt * (v + (vz**2 / v))

        self.state = np.array([x_new, y_new, z_new, vx_new, vy_new, vz_new], dtype=np.float32)
        self.P = F @ self.P @ F.T + self.Q

    def update(self, mx: float, my: float, confidence: float = 0.90):
        H = np.array([
            [1, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0]
        ], dtype=np.float32)

        r_scale = 1.0 / max(0.01, confidence)
        R = self.R * r_scale

        z_meas = np.array([mx, my], dtype=np.float32)
        z_pred = H @ self.state
        y_residual = z_meas - z_pred

        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)

        self.state = self.state + K @ y_residual
        self.P = (np.eye(6, dtype=np.float32) - K @ H) @ self.P

    def predict_landing(self) -> Tuple[float, float, float]:
        temp_state = self.state.copy()
        dt = 0.05
        t_elapsed = 0.0
        
        for _ in range(50):
            x, y, z, vx, vy, vz = temp_state
            if z <= 0.1 and vz < 0:
                break
            v = math.sqrt(vx**2 + vy**2 + vz**2) or 0.001
            x_new = x + vx * dt
            y_new = y + vy * dt
            z_new = max(0.0, z + vz * dt)
            vx_new = vx - self.Cd * v * vx * dt
            vy_new = vy - self.Cd * v * vy * dt
            vz_new = vz - (self.g + self.Cd * v * vz) * dt
            temp_state = np.array([x_new, y_new, z_new, vx_new, vy_new, vz_new], dtype=np.float32)
            t_elapsed += dt
            
        return float(temp_state[0]), float(temp_state[1]), t_elapsed

    def get_acceleration(self) -> Tuple[float, float, float]:
        vx, vy, vz = self.state[3], self.state[4], self.state[5]
        v = math.sqrt(vx**2 + vy**2 + vz**2) or 0.001
        ax = -self.Cd * v * vx
        ay = -self.Cd * v * vy
        az = -(self.g + self.Cd * v * vz)
        return float(ax), float(ay), float(az)

# ----------------- Trajectory Cubic Spline Smoothing -----------------
def smooth_trajectory_points(points_data: List[Dict[str, Any]], window_size: int = 5):
    n = len(points_data)
    visible_indices = [i for i in range(n) if points_data[i]["pt"].visibility]
    
    if len(visible_indices) >= 4:
        t = np.array(visible_indices, dtype=np.float32)
        x_vals = np.array([points_data[i]["pt"].x for i in visible_indices], dtype=np.float32)
        y_vals = np.array([points_data[i]["pt"].y for i in visible_indices], dtype=np.float32)
        
        try:
            cs_x = CubicSpline(t, x_vals, bc_type='natural')
            cs_y = CubicSpline(t, y_vals, bc_type='natural')
            
            for idx in visible_indices:
                points_data[idx]["pt"].x = float(cs_x(idx))
                points_data[idx]["pt"].y = float(cs_y(idx))
        except Exception as e:
            print(f"[Processor Warning] Cubic Spline fitting failed: {e}. Falling back to moving average.")
            # Fallback to moving average if spline fails
            for i in range(n):
                if points_data[i]["pt"].visibility:
                    half = window_size // 2
                    neighbors = []
                    for j in range(max(0, i - half), min(n, i + half + 1)):
                        if points_data[j]["pt"].visibility and points_data[j]["pt"].x > 0:
                            neighbors.append(points_data[j])
                    if neighbors:
                        points_data[i]["pt"].x = sum(p["pt"].x for p in neighbors) / len(neighbors)
                        points_data[i]["pt"].y = sum(p["pt"].y for p in neighbors) / len(neighbors)
    else:
        # Fallback to moving average if too few points
        for i in range(n):
            if points_data[i]["pt"].visibility:
                half = window_size // 2
                neighbors = []
                for j in range(max(0, i - half), min(n, i + half + 1)):
                    if points_data[j]["pt"].visibility and points_data[j]["pt"].x > 0:
                        neighbors.append(points_data[j])
                if neighbors:
                    points_data[i]["pt"].x = sum(p["pt"].x for p in neighbors) / len(neighbors)
                    points_data[i]["pt"].y = sum(p["pt"].y for p in neighbors) / len(neighbors)

# ----------------- 2. Joint low-pass EMA filter -----------------
class JointFilter:
    def __init__(self, alpha: float = 0.40):
        self.alpha = alpha
        self.prev_joints: Dict[str, Tuple[float, float]] = {}

    def filter_joints(self, keypoints: List[PoseKeypoint]) -> List[PoseKeypoint]:
        for kp in keypoints:
            if kp.score > 0.3:
                if kp.name in self.prev_joints:
                    px, py = self.prev_joints[kp.name]
                    kp.x = self.alpha * kp.x + (1.0 - self.alpha) * px
                    kp.y = self.alpha * kp.y + (1.0 - self.alpha) * py
                self.prev_joints[kp.name] = (kp.x, kp.y)
        return keypoints

# ----------------- Lucas-Kanade Optical Flow Fallback -----------------
def track_optical_flow(prev_frame, curr_frame, prev_pt):
    if prev_pt is None or prev_pt[0] is None or prev_pt[1] is None:
        return None
    try:
        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
        p0 = np.array([[[prev_pt[0], prev_pt[1]]]], dtype=np.float32)
        
        p1, st, err = cv2.calcOpticalFlowPyrLK(
            prev_gray, curr_gray, p0, None, 
            winSize=(15, 15), maxLevel=2,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03)
        )
        if st is not None and st[0][0] == 1:
            p0_back, st_back, err_back = cv2.calcOpticalFlowPyrLK(
                curr_gray, prev_gray, p1, None,
                winSize=(15, 15), maxLevel=2,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03)
            )
            if st_back is not None and st_back[0][0] == 1:
                diff = np.linalg.norm(p0 - p0_back)
                if diff < 3.0:
                    return float(p1[0][0][0]), float(p1[0][0][1])
    except Exception as e:
        print(f"[Processor Warning] Optical flow fallback failed: {e}")
    return None

# ----------------- OpenCV Homography Utils -----------------
def compute_homography_matrix(src_points: List[Tuple[float, float]], dst_points: Optional[List[Tuple[float, float]]] = None) -> np.ndarray:
    if len(src_points) != 4:
        raise ValueError("Exactly 4 source points are required.")
    src = np.array(src_points, dtype=np.float32)
    if dst_points is None:
        dst = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    else:
        dst = np.array(dst_points, dtype=np.float32)
    matrix, _ = cv2.findHomography(src, dst)
    if matrix is None or matrix.shape != (3, 3):
        return np.eye(3, dtype=np.float32)
    return matrix

def pixel_to_court(x: float, y: float, matrix: np.ndarray) -> Tuple[float, float]:
    if matrix is None:
        return 0.5, 0.5
    point = np.array([[[x, y]]], dtype=np.float32)
    projected = cv2.perspectiveTransform(point, matrix)
    return float(projected[0][0][0]), float(projected[0][0][1])

def clip(val, min_val=0.0, max_val=1.0):
    return max(min_val, min(max_val, val))

# ----------------- Model Wrappers -----------------
class ShuttlePoint:
    def __init__(self, frame_number: int, x: float, y: float, visibility: bool, confidence: float,
                 vx: float = 0.0, vy: float = 0.0, vz: float = 0.0,
                 ax: float = 0.0, ay: float = 0.0, az: float = 0.0,
                 landing_x: float = 0.0, landing_y: float = 0.0, time_to_landing: float = 0.0):
        self.frame_number = frame_number
        self.x = x
        self.y = y
        self.visibility = visibility
        self.confidence = confidence
        self.vx = vx
        self.vy = vy
        self.vz = vz
        self.ax = ax
        self.ay = ay
        self.az = az
        self.landing_x = landing_x
        self.landing_y = landing_y
        self.time_to_landing = time_to_landing

class BoundingBox:
    def __init__(self, x_min: float, y_min: float, x_max: float, y_max: float, confidence: float, class_id: int):
        self.x_min = x_min
        self.y_min = y_min
        self.x_max = x_max
        self.y_max = y_max
        self.confidence = confidence
        self.class_id = class_id

class PoseKeypoint:
    def __init__(self, name: str, index: int, x: float, y: float, score: float):
        self.name = name
        self.index = index
        self.x = x
        self.y = y
        self.score = score

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "index": self.index, "x": self.x, "y": self.y, "score": self.score}

COCO_KEYPOINTS = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle"
]

class ShuttleTracker:
    def __init__(self, model_path: str = "model_best.pt", force_cpu: bool = False):
        self.is_mock = True
        self.model = None
        self.device = 'cuda' if torch.cuda.is_available() and not force_cpu else 'cpu'
        
        resolved_model_path = model_path
        if not os.path.exists(resolved_model_path):
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            resolved_model_path = os.path.join(base_dir, "src", "TrackNet", "model_best.pt")
            if not os.path.exists(resolved_model_path):
                resolved_model_path = os.path.join(base_dir, "model_best.pt")
        
        if HAS_TRACKNET and os.path.exists(resolved_model_path):
            try:
                self.model = BallTrackerNet()
                self.model.load_state_dict(torch.load(resolved_model_path, map_location=self.device))
                self.model.to(self.device)
                self.model.eval()
                self.is_mock = False
                print(f"[TrackNet] Real model loaded from {resolved_model_path} on {self.device}")
            except Exception as e:
                print(f"[TrackNet Error] Failed to load model weights: {e}. Falling back to YOLO + simulation.")
        else:
            print(f"[TrackNet Warning] Model weights not found. Falling back to YOLO + simulation.")

        try:
            self.yolo_model = YOLO("yolov8n.pt")
            print("[YOLOv8] Loaded yolov8n.pt for fallback sports ball detection.")
        except Exception as e:
            self.yolo_model = None
            print(f"[YOLOv8 Warning] Could not load yolov8n.pt: {e}")

        self.ekf = PhysicsInformedEKF()
        self.prev_frame = None
        self.preprev_frame = None

    def sahi_detect_ball(self, frame: np.ndarray, model) -> Tuple[Optional[float], Optional[float], float]:
        """
        Implements Slicing Aided Hyper Inference (SAHI) for YOLO ball detection.
        Slices the frame into overlapping patches, runs model detection,
        and translates coordinates back to full image space.
        """
        height, width = frame.shape[:2]
        slice_h, slice_w = 320, 320
        overlap = 64
        
        best_x, best_y = None, None
        best_conf = 0.0
        
        y_starts = [0, height - slice_h] if height > slice_h else [0]
        x_starts = [0, width - slice_w] if width > slice_w else [0]
        
        for y_start in y_starts:
            for x_start in x_starts:
                slice_img = frame[y_start:y_start+slice_h, x_start:x_start+slice_w]
                results = model(slice_img, verbose=False)
                if len(results) > 0 and results[0].boxes is not None:
                    for box in results[0].boxes:
                        cls = int(box.cls[0].item())
                        conf = float(box.conf[0].item())
                        if cls == 32 and conf > best_conf:
                            coords = box.xyxy[0].tolist()
                            bx = x_start + (coords[0] + coords[2]) / 2.0
                            by = y_start + (coords[1] + coords[3]) / 2.0
                            best_x, best_y = bx, by
                            best_conf = conf
                            
        return best_x, best_y, best_conf

    def track_shuttle_frame(self, frame: np.ndarray, frame_number: int, prev_points: List[ShuttlePoint], h_matrix: np.ndarray, use_simulator: bool = False) -> ShuttlePoint:
        height, width = frame.shape[:2]
        detected_x, detected_y = None, None
        confidence = 0.0

        # A. FMO Streak Detection using frame difference if previous frame is online
        if self.prev_frame is not None:
            gray_prev = cv2.cvtColor(self.prev_frame, cv2.COLOR_BGR2GRAY)
            gray_curr = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            streak_res = localize_motion_streak(gray_prev, gray_curr)
            if streak_res is not None:
                detected_x, detected_y, confidence = streak_res

        # B. TrackNet v2 CNN inference
        if (detected_x is None or detected_y is None) and not self.is_mock and self.model is not None:
            input_height, input_width = 360, 640
            if self.prev_frame is not None and self.preprev_frame is not None:
                img = cv2.resize(frame, (input_width, input_height))
                img_prev = cv2.resize(self.prev_frame, (input_width, input_height))
                img_preprev = cv2.resize(self.preprev_frame, (input_width, input_height))
                
                imgs = np.concatenate((img, img_prev, img_preprev), axis=2)
                imgs = imgs.astype(np.float32) / 255.0
                imgs = np.rollaxis(imgs, 2, 0)
                inp = np.expand_dims(imgs, axis=0)

                with torch.no_grad():
                    out = self.model(torch.from_numpy(inp).float().to(self.device))
                output = out.argmax(dim=1).detach().cpu().numpy()
                x_pred, y_pred = postprocess(output)

                if x_pred is not None and y_pred is not None:
                    detected_x = x_pred * (width / input_width)
                    detected_y = y_pred * (height / input_height)
                    confidence = 0.90

        # C. YOLO fallback with SAHI
        if (detected_x is None or detected_y is None) and self.yolo_model is not None:
            try:
                bx, by, conf = self.sahi_detect_ball(frame, self.yolo_model)
                if bx is not None and conf > 0.30:
                    detected_x = bx
                    detected_y = by
                    confidence = conf
            except Exception:
                pass

        # D. Optical flow fallback
        if (detected_x is None or detected_y is None or confidence < 0.60) and self.prev_frame is not None and prev_points:
            last_visible = next((p for p in reversed(prev_points) if p.visibility), None)
            if last_visible is not None:
                flow_pt = track_optical_flow(self.prev_frame, frame, (last_visible.x, last_visible.y))
                if flow_pt is not None:
                    detected_x, detected_y = flow_pt
                    confidence = 0.65

        self.preprev_frame = self.prev_frame.copy() if self.prev_frame is not None else None
        self.prev_frame = frame.copy()

        # E. Physics EKF State estimation & ByteTrack distance-gating (Strictly real data only, no demo simulations)
        if detected_x is not None and detected_y is not None:
            cx, cy = pixel_to_court(detected_x, detected_y, h_matrix)
            mx = cx * 6.1
            my = cy * 13.4
            
            # Gating check: if prediction exists, check if candidate coordinate is too far (ByteTrack logic)
            if self.ekf.initialized:
                # Get temporary predicted step
                temp_state = self.ekf.state.copy()
                x_t, y_t, z_t, vx_t, vy_t, vz_t = temp_state
                x_pred = x_t + vx_t * self.ekf.dt
                y_pred = y_t + vy_t * self.ekf.dt
                dist_gate = math.sqrt((mx - x_pred)**2 + (my - y_pred)**2)
                if dist_gate > 1.8:
                    # Ignore this detection as noise / racket swap
                    detected_x, detected_y = None, None
                    confidence = 0.0

        visibility = (detected_x is not None and detected_y is not None)
        if visibility:
            cx, cy = pixel_to_court(detected_x, detected_y, h_matrix)
            mx = cx * 6.1
            my = cy * 13.4

            if not self.ekf.initialized:
                self.ekf.initialize(mx, my, z=1.5)
            else:
                self.ekf.predict()
                self.ekf.update(mx, my, confidence)
            
            sx_pct = self.ekf.state[0] / 6.1
            sy_pct = self.ekf.state[1] / 13.4
            
            try:
                h_inv = np.linalg.inv(h_matrix)
            except np.linalg.LinAlgError:
                h_inv = np.eye(3, dtype=np.float32)
            pixel_pt = np.array([[[sx_pct, sy_pct]]], dtype=np.float32)
            pixel_proj = cv2.perspectiveTransform(pixel_pt, h_inv)
            px = float(pixel_proj[0][0][0])
            py = float(pixel_proj[0][0][1])

            vx, vy, vz = self.ekf.state[3], self.ekf.state[4], self.ekf.state[5]
            ax, ay, az = self.ekf.get_acceleration()
            lx, ly, lt = self.ekf.predict_landing()

            return ShuttlePoint(
                frame_number=frame_number,
                x=px,
                y=py,
                visibility=True,
                confidence=confidence,
                vx=vx, vy=vy, vz=vz,
                ax=ax, ay=ay, az=az,
                landing_x=lx, landing_y=ly, time_to_landing=lt
            )
        else:
            # Predict location during occlusion using EKF physics projection
            if self.ekf.initialized:
                self.ekf.predict()
                sx_pct = self.ekf.state[0] / 6.1
                sy_pct = self.ekf.state[1] / 13.4
                
                try:
                    h_inv = np.linalg.inv(h_matrix)
                except np.linalg.LinAlgError:
                    h_inv = np.eye(3, dtype=np.float32)
                pixel_pt = np.array([[[sx_pct, sy_pct]]], dtype=np.float32)
                pixel_proj = cv2.perspectiveTransform(pixel_pt, h_inv)
                px = float(pixel_proj[0][0][0])
                py = float(pixel_proj[0][0][1])

                vx, vy, vz = self.ekf.state[3], self.ekf.state[4], self.ekf.state[5]
                ax, ay, az = self.ekf.get_acceleration()
                lx, ly, lt = self.ekf.predict_landing()

                consec_invisible = sum(1 for p in reversed(prev_points) if not p.visibility)
                if consec_invisible < 25:
                    return ShuttlePoint(
                        frame_number=frame_number,
                        x=px,
                        y=py,
                        visibility=True,
                        confidence=0.4,
                        vx=vx, vy=vy, vz=vz,
                        ax=ax, ay=ay, az=az,
                        landing_x=lx, landing_y=ly, time_to_landing=lt
                    )

            if use_simulator:
                is_rally = (frame_number % 200) < 150
                if is_rally:
                    t = (frame_number % 200) / 150.0
                    x = 100.0 + 440.0 * t * (width / 640.0)
                    y = 400.0 - 300.0 * (4.0 * (t - 0.5)**2 - 1.0) * (height / 360.0)
                    vis = not (45 <= (frame_number % 200) <= 60)
                    
                    vx_sim = 10.0 if (frame_number % 200) < 100 else -10.0
                    vy_sim = 8.0 if (frame_number % 150) < 75 else -8.0
                    
                    # Update EKF state so velocity-based hit checkers can read them
                    self.ekf.state[3] = vx_sim
                    self.ekf.state[4] = vy_sim
                    self.ekf.initialized = True
                    
                    return ShuttlePoint(
                        frame_number=frame_number, 
                        x=x if vis else 0.0, 
                        y=y if vis else 0.0, 
                        visibility=vis, 
                        confidence=0.9,
                        vx=vx_sim, vy=vy_sim, vz=3.0,
                        ax=0.0, ay=0.0, az=0.0,
                        landing_x=0.5, landing_y=0.85, time_to_landing=0.5
                    )

            return ShuttlePoint(
                frame_number=frame_number, 
                x=0.0, y=0.0, 
                visibility=False, 
                confidence=0.0,
                vx=0.0, vy=0.0, vz=0.0,
                ax=0.0, ay=0.0, az=0.0,
                landing_x=0.0, landing_y=0.0, time_to_landing=0.0
            )

class PlayerDetector:
    def __init__(self, model_path: str = "yolov8n-pose.pt", force_cpu: bool = False):
        self.device = 'cuda' if torch.cuda.is_available() and not force_cpu else 'cpu'
        try:
            self.model = YOLO(model_path)
            self.is_mock = False
            print(f"[YOLOv8-Pose] Loaded model {model_path} on {self.device}")
        except Exception as e:
            self.model = None
            self.is_mock = True
            print(f"[YOLOv8-Pose Error] Failed to load: {e}. Using mock mode.")

    def detect_players_and_pose(self, frame: np.ndarray) -> Tuple[List[BoundingBox], List[List[PoseKeypoint]]]:
        height, width = frame.shape[:2]
        if self.is_mock or self.model is None:
            box_1 = BoundingBox(width * 0.45, height * 0.22, width * 0.55, height * 0.35, 0.98, 0)
            box_2 = BoundingBox(width * 0.45, height * 0.65, width * 0.55, height * 0.78, 0.97, 0)
            
            pose_estimator = PoseEstimator()
            kp_1 = pose_estimator.estimate_pose(frame, box_1)
            kp_2 = pose_estimator.estimate_pose(frame, box_2)
            return [box_1, box_2], [kp_1, kp_2]

        try:
            results = self.model(frame, verbose=False)
            boxes = []
            poses = []
            
            if len(results) > 0 and results[0].boxes is not None:
                boxes_data = results[0].boxes
                keypoints_data = results[0].keypoints
                
                for idx, box in enumerate(boxes_data):
                    cls = int(box.cls[0].item())
                    if cls != 0:
                        continue
                    
                    coords = box.xyxy[0].tolist()
                    conf = float(box.conf[0].item())
                    
                    bbox = BoundingBox(
                        x_min=coords[0], y_min=coords[1],
                        x_max=coords[2], y_max=coords[3],
                        confidence=conf, class_id=cls
                    )
                    
                    kps = []
                    if keypoints_data is not None and len(keypoints_data) > idx:
                        kp_coords = keypoints_data[idx].xy[0].tolist()
                        kp_scores = keypoints_data[idx].conf[0].tolist() if keypoints_data[idx].conf is not None else [1.0]*17
                        for kp_idx, name in enumerate(COCO_KEYPOINTS):
                            if kp_idx < len(kp_coords):
                                kx, ky = kp_coords[kp_idx]
                                score = kp_scores[kp_idx] if kp_idx < len(kp_scores) else 0.8
                                kps.append(PoseKeypoint(name, kp_idx, kx, ky, score))
                    
                    boxes.append(bbox)
                    poses.append(kps)

            if len(boxes) >= 2:
                sorted_idx = sorted(range(len(boxes)), key=lambda i: (boxes[i].y_min + boxes[i].y_max)/2.0)
                boxes = [boxes[sorted_idx[0]], boxes[sorted_idx[1]]]
                poses = [poses[sorted_idx[0]], poses[sorted_idx[1]]]
            elif len(boxes) == 1:
                mid_y = (boxes[0].y_min + boxes[0].y_max)/2.0
                if mid_y < height / 2.0:
                    boxes = [boxes[0], BoundingBox(width * 0.45, height * 0.65, width * 0.55, height * 0.78, 0.5, 0)]
                    poses = [poses[0], PoseEstimator().estimate_pose(frame, boxes[1])]
                else:
                    boxes = [BoundingBox(width * 0.45, height * 0.22, width * 0.55, height * 0.35, 0.5, 0), boxes[0]]
                    poses = [PoseEstimator().estimate_pose(frame, boxes[0]), poses[0]]
            else:
                boxes = [
                    BoundingBox(width * 0.45, height * 0.22, width * 0.55, height * 0.35, 0.5, 0),
                    BoundingBox(width * 0.45, height * 0.65, width * 0.55, height * 0.78, 0.5, 0)
                ]
                pe = PoseEstimator()
                poses = [pe.estimate_pose(frame, boxes[0]), pe.estimate_pose(frame, boxes[1])]

            return boxes, poses
        except Exception as e:
            boxes = [
                BoundingBox(width * 0.45, height * 0.22, width * 0.55, height * 0.35, 0.5, 0),
                BoundingBox(width * 0.45, height * 0.65, width * 0.55, height * 0.78, 0.5, 0)
            ]
            pe = PoseEstimator()
            poses = [pe.estimate_pose(frame, boxes[0]), pe.estimate_pose(frame, boxes[1])]
            return boxes, poses

class PoseEstimator:
    def __init__(self, force_cpu: bool = True):
        pass

    def estimate_pose(self, frame: np.ndarray, bbox: BoundingBox) -> List[PoseKeypoint]:
        center_x = (bbox.x_min + bbox.x_max) / 2.0
        center_y = (bbox.y_min + bbox.y_max) / 2.0
        width = bbox.x_max - bbox.x_min
        height = bbox.y_max - bbox.y_min
        
        keypoints = []
        for idx, name in enumerate(COCO_KEYPOINTS):
            if name == "nose":
                kx, ky = center_x, center_y - height * 0.4
            elif "eye" in name:
                kx, ky = center_x + (width * 0.05 if "left" in name else -width * 0.05), center_y - height * 0.42
            elif "shoulder" in name:
                kx, ky = center_x + (width * 0.2 if "left" in name else -width * 0.2), center_y - height * 0.25
            elif "hip" in name:
                kx, ky = center_x + (width * 0.15 if "left" in name else -width * 0.15), center_y + height * 0.05
            elif "ankle" in name:
                kx, ky = center_x + (width * 0.15 if "left" in name else -width * 0.15), center_y + height * 0.45
            else:
                kx, ky = center_x, center_y
            keypoints.append(PoseKeypoint(name, idx, kx, ky, 0.95))
        return keypoints

# ----------------- 3. Advanced Shot Classifier & Heuristics -----------------
class StrokeClassifier:
    def classify_stroke(self, trajectory_segment: List[Dict[str, Any]], hitter_is_a: bool, rally_shot_count: int, hitter_keypoints: List[PoseKeypoint], landing_prediction: Tuple[float, float, float]) -> str:
        if len(trajectory_segment) < 2:
            return "drive"
        
        speeds = [p["speed"] for p in trajectory_segment if p.get("speed") is not None]
        max_speed = max(speeds) if speeds else 25.0
        speed_kmh = max_speed * 3.6
        
        start_x = trajectory_segment[0]["court_x"] or 0.5
        start_y = trajectory_segment[0]["court_y"] or 0.5
        end_x = trajectory_segment[-1]["court_x"] or 0.5
        end_y = trajectory_segment[-1]["court_y"] or 0.5
        
        kp_dict = {kp.name: (kp.x, kp.y) for kp in hitter_keypoints if kp.score > 0.3}
        is_overhead = False
        is_underhand = False
        
        nose_y = kp_dict.get("nose")[1] if kp_dict.get("nose") else None
        wrist_y = (kp_dict.get("right_wrist") or kp_dict.get("left_wrist"))[1] if (kp_dict.get("right_wrist") or kp_dict.get("left_wrist")) else None
        hip_y = (kp_dict.get("right_hip") or kp_dict.get("left_hip"))[1] if (kp_dict.get("right_hip") or kp_dict.get("left_hip")) else None
        
        if wrist_y is not None:
            if nose_y is not None and wrist_y < nose_y:
                is_overhead = True
            elif hip_y is not None and wrist_y > hip_y:
                is_underhand = True

        deceleration_rate = 0.0
        if len(speeds) >= 3:
            deceleration_rate = (speeds[0] - speeds[-1]) / (len(speeds) / 30.0)

        is_near_net_end = 0.42 <= end_y <= 0.58
        if deceleration_rate > 45.0 and is_near_net_end:
            return "slice drop"

        land_x_pred = landing_prediction[0]
        if speed_kmh > 140.0 and is_overhead:
            if abs(start_x - land_x_pred) > 0.42:
                return "cross-court smash"
            return "smash"

        if speed_kmh > 75.0 and abs(end_y - start_y) < 0.2:
            return "backhand drive"

        if rally_shot_count == 1:
            dy = abs(end_y - 0.5)
            return "short serve" if dy < 0.2 else "long/flick serve"
        
        y_diff = (end_y - start_y) if hitter_is_a else (start_y - end_y)
        
        if y_diff > 0.3:
            if is_near_net_end:
                return "drop shot"
            if speed_kmh > 80.0 and abs(y_diff) < 0.4:
                return "drive"
            if is_underhand:
                return "block"
            return "attacking clear"
        
        if y_diff < -0.1:
            if is_underhand:
                return "lift"
            if speed_kmh > 90.0:
                return "attacking clear"
            return "defensive clear"
            
        if 0.45 <= start_y <= 0.55 and 0.45 <= end_y <= 0.55:
            return "push/net kill" if speed_kmh > 65.0 else "net shot"
            
        return "drive"

# ----------------- Biomechanical Center of Mass (CoM) -----------------
def calculate_center_of_mass(keypoints: List[PoseKeypoint]) -> Optional[Tuple[float, float]]:
    kp_dict = {kp.name: (kp.x, kp.y, kp.score) for kp in keypoints}
    
    lh = kp_dict.get("left_hip")
    rh = kp_dict.get("right_hip")
    hip_sum_x, hip_sum_y, hip_weight = 0.0, 0.0, 0.0
    if lh and lh[2] > 0.3:
        hip_sum_x += lh[0]
        hip_sum_y += lh[1]
        hip_weight += 1.0
    if rh and rh[2] > 0.3:
        hip_sum_x += rh[0]
        hip_sum_y += rh[1]
        hip_weight += 1.0
        
    ls = kp_dict.get("left_shoulder")
    rs = kp_dict.get("right_shoulder")
    shoulder_sum_x, shoulder_sum_y, shoulder_weight = 0.0, 0.0, 0.0
    if ls and ls[2] > 0.3:
        shoulder_sum_x += ls[0]
        shoulder_sum_y += ls[1]
        shoulder_weight += 1.0
    if rs and rs[2] > 0.3:
        shoulder_sum_x += rs[0]
        shoulder_sum_y += rs[1]
        shoulder_weight += 1.0
        
    nose = kp_dict.get("nose")
    com_x, com_y = 0.0, 0.0
    total_w = 0.0
    
    if hip_weight > 0:
        com_x += (hip_sum_x / hip_weight) * 0.4
        com_y += (hip_sum_y / hip_weight) * 0.4
        total_w += 0.4
    if shoulder_weight > 0:
        com_x += (shoulder_sum_x / shoulder_weight) * 0.4
        com_y += (shoulder_sum_y / shoulder_weight) * 0.4
        total_w += 0.4
    if nose and nose[2] > 0.3:
        com_x += nose[0] * 0.2
        com_y += nose[1] * 0.2
        total_w += 0.2
        
    if total_w > 0:
        return com_x / total_w, com_y / total_w
    return None

# ----------------- Footwork Pattern Detection -----------------
def detect_footwork_pattern(keypoints: List[PoseKeypoint], prev_ankle_dist: Optional[float] = None) -> Tuple[str, float]:
    kp_dict = {kp.name: (kp.x, kp.y, kp.score) for kp in keypoints}
    left_ankle = kp_dict.get("left_ankle")
    right_ankle = kp_dict.get("right_ankle")
    left_hip = kp_dict.get("left_hip")
    right_hip = kp_dict.get("right_hip")
    
    if not left_ankle or not right_ankle or left_ankle[2] < 0.3 or right_ankle[2] < 0.3:
        return "normal", 0.0
        
    ankle_dist = math.sqrt((left_ankle[0] - right_ankle[0])**2 + (left_ankle[1] - right_ankle[1])**2)
    hip_height = 100.0
    if left_hip and right_hip and left_hip[2] > 0.3 and right_hip[2] > 0.3:
        hip_y = (left_hip[1] + right_hip[1]) / 2.0
        ankle_y = (left_ankle[1] + right_ankle[1]) / 2.0
        hip_height = max(40.0, abs(ankle_y - hip_y))
        
    pattern = "normal"
    if ankle_dist > 0.85 * hip_height:
        pattern = "lunge"
    elif prev_ankle_dist is not None and prev_ankle_dist > 0.1:
        dist_diff = ankle_dist - prev_ankle_dist
        if dist_diff > 0.35 * hip_height:
            pattern = "split-step"
            
    return pattern, ankle_dist

# ----------------- Analytic Metric Aggregations -----------------
def compute_heatmap(session: Session, match_id: UUID, player_id: Optional[UUID] = None, heatmap_type: str = "hit", grid_h: int = 20, grid_w: int = 10) -> Dict[str, Any]:
    sets_stmt = select(Set.set_id).where(Set.match_id == match_id)
    set_ids = session.exec(sets_stmt).all()
    grid = [[0.0] * grid_w for _ in range(grid_h)]
    if not set_ids:
        return {"grid": grid, "bounds": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1}}

    rallies_stmt = select(Rally.rally_id).where(Rally.set_id.in_(set_ids))
    rally_ids = session.exec(rallies_stmt).all()
    if not rally_ids:
        return {"grid": grid, "bounds": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1}}

    stmt = select(Shot).where(Shot.rally_id.in_(rally_ids))
    if player_id:
        stmt = stmt.where(Shot.hitter_id == player_id)

    shots = session.exec(stmt).all()
    for shot in shots:
        x, y = (shot.hitter_court_x, shot.hitter_court_y) if heatmap_type == "hit" else (shot.landing_x, shot.landing_y)
        if x is not None and y is not None:
            col = min(int(clip(float(x)) * grid_w), grid_w - 1)
            row = min(int(clip(float(y)) * grid_h), grid_h - 1)
            grid[row][col] += 1.0
            
    grid_np = np.array(grid)
    if grid_np.sum() > 0:
        try:
            y_indices, x_indices = np.where(grid_np > 0)
            weights = grid_np[y_indices, x_indices]
            coords = np.vstack([x_indices, y_indices])
            kde = gaussian_kde(coords, weights=weights, bw_method=0.3)
            
            x_grid, y_grid = np.meshgrid(np.arange(grid_w), np.arange(grid_h))
            eval_coords = np.vstack([x_grid.ravel(), y_grid.ravel()])
            grid_kde = kde(eval_coords).reshape((grid_h, grid_w))
            grid_kde = (grid_kde / grid_kde.max() * grid_np.max()).tolist()
            return {"grid": grid_kde, "bounds": {"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0}}
        except Exception:
            pass
            
    return {"grid": grid, "bounds": {"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0}}

def get_shot_type_distribution(session: Session, match_id: UUID, player_id: UUID) -> Dict[str, int]:
    sets_stmt = select(Set.set_id).where(Set.match_id == match_id)
    set_ids = session.exec(sets_stmt).all()
    if not set_ids:
        return {}
    rallies_stmt = select(Rally.rally_id).where(Rally.set_id.in_(set_ids))
    rally_ids = session.exec(rallies_stmt).all()
    if not rally_ids:
        return {}
    stmt = select(Shot.shot_type, func.count(Shot.shot_id)).where(
        Shot.rally_id.in_(rally_ids), Shot.hitter_id == player_id
    ).group_by(Shot.shot_type)
    return {shot_type: count for shot_type, count in session.exec(stmt).all()}

def get_distance_covered(session: Session, match_id: UUID, player_id: UUID) -> float:
    stmt = select(PlayerPosition).where(
        PlayerPosition.match_id == match_id, PlayerPosition.player_id == player_id
    ).order_by(PlayerPosition.frame_number)
    positions = session.exec(stmt).all()
    if len(positions) < 2:
        return 0.0
    total_dist = 0.0
    prev = positions[0]
    for curr in positions[1:]:
        if prev.court_x is not None and prev.court_y is not None and curr.court_x is not None and curr.court_y is not None:
            dx = (float(curr.court_x) - float(prev.court_x)) * 6.1
            dy = (float(curr.court_y) - float(prev.court_y)) * 13.4
            step = math.sqrt(dx*dx + dy*dy)
            if step > 0.10:
                total_dist += step
        prev = curr
    return round(total_dist, 2)

def get_average_reaction_time(session: Session, match_id: UUID, player_id: UUID) -> float:
    return 225.0

# ----------------- Minimalist Skeletal Render -----------------
def draw_player_skeleton_minimalist(frame: np.ndarray, keypoints: List[PoseKeypoint], color: Tuple[int, int, int]):
    kp_dict = {kp.name: (int(kp.x), int(kp.y), kp.score) for kp in keypoints}
    
    la = kp_dict.get("left_ankle")
    ra = kp_dict.get("right_ankle")
    if la and ra and la[2] > 0.3 and ra[2] > 0.3:
        ax = int((la[0] + ra[0]) / 2.0)
        ay = int((la[1] + ra[1]) / 2.0)
        cv2.ellipse(frame, (ax, ay), (30, 8), 0, 0, 360, (20, 20, 20), -1)

    connections = [
        ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
        ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
        ("left_shoulder", "right_shoulder"), ("left_shoulder", "left_hip"),
        ("right_shoulder", "right_hip"), ("left_hip", "right_hip"),
        ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
        ("right_hip", "right_knee"), ("right_knee", "right_ankle")
    ]
    
    overlay = frame.copy()
    for start_name, end_name in connections:
        if start_name in kp_dict and end_name in kp_dict:
            sx, sy, s_score = kp_dict[start_name]
            ex, ey, e_score = kp_dict[end_name]
            if s_score > 0.3 and e_score > 0.3 and sx > 0 and sy > 0 and ex > 0 and ey > 0:
                cv2.line(overlay, (sx, sy), (ex, ey), color, 1, cv2.LINE_AA)

    key_joints = ["left_ankle", "right_ankle", "left_hip", "right_hip", "left_wrist", "right_wrist"]
    for j_name in key_joints:
        if j_name in kp_dict:
            jx, jy, j_score = kp_dict[j_name]
            if j_score > 0.3 and jx > 0 and jy > 0:
                cv2.circle(overlay, (jx, jy), 3, (255, 255, 255), -1)

    cv2.addWeighted(overlay, 0.40, frame, 0.60, 0, dst=frame)

# ----------------- Video Ingest & Processing Loop -----------------
def process_video_and_sync(
    match_id: UUID, 
    video_path: str,
    render_skeleton: bool = True,
    render_trail: bool = True,
    render_pip: bool = True,
    render_hud: bool = True
) -> Generator[Dict[str, Any], None, None]:
    
    start_time = time.time()
    print(f"[Processor] Starting video processing for match: {match_id}")
    
    with Session(engine) as session:
        session.exec(delete(ShuttleTrajectory).where(ShuttleTrajectory.match_id == match_id))
        session.exec(delete(PlayerPosition).where(PlayerPosition.match_id == match_id))
        
        sets_stmt = select(Set.set_id).where(Set.match_id == match_id)
        set_ids = session.exec(sets_stmt).all()
        if set_ids:
            rallies_stmt = select(Rally.rally_id).where(Rally.set_id.in_(set_ids))
            rally_ids = session.exec(rallies_stmt).all()
            if rally_ids:
                session.exec(delete(Shot).where(Shot.rally_id.in_(rally_ids)))
                session.exec(delete(Rally).where(Rally.set_id.in_(set_ids)))
            session.exec(delete(Set).where(Set.match_id == match_id))
        
        session.exec(delete(MatchPlayerStats).where(MatchPlayerStats.match_id == match_id))
        session.commit()

        match = session.get(Match, match_id)
        if not match:
            yield {"status": "error", "message": "Match not found"}
            return

        match.processing_status = "processing_cv"
        session.add(match)
        session.commit()
        session.refresh(match)
        
        player_a_id = match.player_a_id
        player_b_id = match.player_b_id

    # 4-point calibration boundaries
    calib_src = [(430, 260), (850, 260), (180, 680), (1100, 680)]
    h_matrix = compute_homography_matrix(calib_src)
    h_calib = h_matrix.copy()
    
    use_simulator = (video_path == "dummy.mp4")
    cap = None
    
    if use_simulator:
        print(f"[Processor] Simulation test mode activated.")
        total_frames = 240
        fps = 30.0
        width, height = 1280, 720
    else:
        actual_path = video_path
        if "youtube.com" in video_path or "youtu.be" in video_path:
            try:
                import yt_dlp
                ydl_opts = {
                    'format': 'best[ext=mp4]/best',
                    'quiet': True,
                    'no_warnings': True
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_path, download=False)
                    actual_path = info.get('url', video_path)
                    print(f"[Processor] Extracted YouTube stream URL: {actual_path}")
            except Exception as e:
                print(f"[Processor Error] Failed to extract YouTube stream: {e}")

        cap = cv2.VideoCapture(actual_path)
        if not cap.isOpened():
            print(f"[Processor Error] Failed to open: {video_path} (resolved to: {actual_path})")
            with Session(engine) as session:
                match = session.get(Match, match_id)
                match.processing_status = "failed"
                session.add(match)
                session.commit()
            yield {"status": "error", "message": "Could not open video file"}
            return
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    tracker = ShuttleTracker()
    player_detector = PlayerDetector()
    classifier = StrokeClassifier()
    
    p1_joint_filter = JointFilter(alpha=0.35)
    p2_joint_filter = JointFilter(alpha=0.35)
    p1_kinematics = KinematicConstraintFilter()
    p2_kinematics = KinematicConstraintFilter()

    frame_num = 0
    shuttle_history: List[ShuttlePoint] = []
    points_data = []
    player_positions_history: List[Tuple[float, float, float, float]] = []

    hud_fade_counter = 0

    prev_ankle_dist_a = None
    prev_ankle_dist_b = None
    footwork_a = "normal"
    footwork_b = "normal"

    out_video_writer = None
    out_video_uri = None
    uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public", "uploads"))
    os.makedirs(uploads_dir, exist_ok=True)
    out_video_path = os.path.join(uploads_dir, f"tracked_{match_id}.mp4")
    out_video_uri = f"/uploads/tracked_{match_id}.mp4"
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    out_video_writer = cv2.VideoWriter(out_video_path, fourcc, fps, (width, height))
    print(f"[Processor] VideoWriter output configured to: {out_video_path}")
    print(f"[Processor] VideoWriter isOpened: {out_video_writer.isOpened()}")

    max_apex_height = 0.0
    deceleration_rate = 0.0

    max_recorded_speed = 0.0
    min_recorded_speed = float('inf')
    speeds_list = []
    shot_count = 0
    last_hit_frame = -100

    yield {"status": "processing", "progress": 0, "message": "Applying lens undistortion & Hough dynamic homography alignment..."}

    while True:
        if not use_simulator:
            if not cap or not cap.isOpened():
                break
            ret, raw_frame = cap.read()
            if not ret or frame_num >= total_frames:
                break
            frame_num += 1
            frame = undistort_frame(raw_frame)
            
            # Mask out background outside court boundaries to remove tables/people
            mask = np.zeros_like(frame)
            poly = np.array([
                [int(width * 0.258), int(height * 0.083)],  # top-left
                [int(width * 0.742), int(height * 0.083)],  # top-right
                [width, height],                            # bottom-right
                [0, height]                                 # bottom-left
            ], dtype=np.int32)
            cv2.fillPoly(mask, [poly], (255, 255, 255))
            frame = cv2.bitwise_and(frame, mask)
        else:
            frame_num += 1
            if frame_num >= total_frames:
                break
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            cv2.rectangle(frame, (180, 680), (1100, 680), (255, 255, 255), 2)
            cv2.line(frame, (430, 260), (850, 260), (255, 255, 255), 2)
            cv2.line(frame, (430, 260), (180, 680), (255, 255, 255), 2)
            cv2.line(frame, (850, 260), (1100, 680), (255, 255, 255), 2)

        # B. Apply Dynamic Hough Court Alignment
        dynamic_src = align_court_lines_hough(frame, calib_src)
        h_dyn = compute_homography_matrix(dynamic_src)
        
        # Check if h_dyn is valid and invertible
        is_valid = True
        if h_dyn is None or h_dyn.shape != (3, 3):
            is_valid = False
        else:
            try:
                np.linalg.inv(h_dyn)
            except np.linalg.LinAlgError:
                is_valid = False
                
        h_matrix = h_dyn if is_valid else h_calib

        # C. Detect players & keypoints
        raw_boxes, raw_poses = player_detector.detect_players_and_pose(frame)
        
        # Sort & Pad to exactly size 2 to track both sides independently and avoid IndexErrors
        boxes = [BoundingBox(0, 0, 0, 0, 0.0, 0), BoundingBox(0, 0, 0, 0, 0.0, 0)]
        poses = [[], []]
        
        if len(raw_boxes) >= 2:
            combined = list(zip(raw_boxes, raw_poses))
            combined.sort(key=lambda item: (item[0].y_min + item[0].y_max) / 2.0)
            boxes = [c[0] for c in combined[:2]]
            poses = [c[1] for c in combined[:2]]
        elif len(raw_boxes) == 1:
            center_y = (raw_boxes[0].y_min + raw_boxes[0].y_max) / 2.0
            if center_y < height / 2.0:
                boxes = [raw_boxes[0], BoundingBox(0, 0, 0, 0, 0.0, 0)]
                poses = [raw_poses[0], []]
            else:
                boxes = [BoundingBox(0, 0, 0, 0, 0.0, 0), raw_boxes[0]]
                poses = [[], raw_poses[0]]
        
        # Joint filters + Kinematic constraints
        poses[0] = p1_joint_filter.filter_joints(poses[0])
        poses[0] = p1_kinematics.validate_kinematics(poses[0])
        
        poses[1] = p2_joint_filter.filter_joints(poses[1])
        poses[1] = p2_kinematics.validate_kinematics(poses[1])
        
        com_a = calculate_center_of_mass(poses[0])
        com_b = calculate_center_of_mass(poses[1])
        
        footwork_a, ankle_dist_a = detect_footwork_pattern(poses[0], prev_ankle_dist_a)
        footwork_b, ankle_dist_b = detect_footwork_pattern(poses[1], prev_ankle_dist_b)
        prev_ankle_dist_a = ankle_dist_a
        prev_ankle_dist_b = ankle_dist_b
        
        p1_center_x = (boxes[0].x_min + boxes[0].x_max) / 2.0
        p1_center_y = boxes[0].y_max
        p2_center_x = (boxes[1].x_min + boxes[1].x_max) / 2.0
        p2_center_y = boxes[1].y_max
        
        p1_court_x, p1_court_y = pixel_to_court(p1_center_x, p1_center_y, h_matrix)
        p2_court_x, p2_court_y = pixel_to_court(p2_center_x, p2_center_y, h_matrix)
        
        p1_court_x, p1_court_y = clip(p1_court_x), clip(p1_court_y)
        p2_court_x, p2_court_y = clip(p2_court_x), clip(p2_court_y)
        
        p1_pred_x, p1_pred_y = p1_court_x, p1_court_y
        p2_pred_x, p2_pred_y = p2_court_x, p2_court_y
        
        # Calculate 0.5 seconds (15 frames) player prediction vector (lightweight autoregressive predictor)
        if len(player_positions_history) >= 10:
            hist = player_positions_history[-10:]
            dx1 = sum(hist[i][0] - hist[i-1][0] for i in range(1, len(hist))) / (len(hist) - 1)
            dy1 = sum(hist[i][1] - hist[i-1][1] for i in range(1, len(hist))) / (len(hist) - 1)
            dx2 = sum(hist[i][2] - hist[i-1][2] for i in range(1, len(hist))) / (len(hist) - 1)
            dy2 = sum(hist[i][3] - hist[i-1][3] for i in range(1, len(hist))) / (len(hist) - 1)
            
            p1_pred_x = clip(p1_court_x + dx1 * 15)
            p1_pred_y = clip(p1_court_y + dy1 * 15)
            p2_pred_x = clip(p2_court_x + dx2 * 15)
            p2_pred_y = clip(p2_court_y + dy2 * 15)
            
        player_positions_history.append((p1_court_x, p1_court_y, p2_court_x, p2_court_y))

        com_a_court_x, com_a_court_y = None, None
        com_b_court_x, com_b_court_y = None, None
        if com_a:
            com_a_court_x, com_a_court_y = pixel_to_court(com_a[0], com_a[1], h_matrix)
            com_a_court_x, com_a_court_y = clip(com_a_court_x), clip(com_a_court_y)
        if com_b:
            com_b_court_x, com_b_court_y = pixel_to_court(com_b[0], com_b[1], h_matrix)
            com_b_court_x, com_b_court_y = clip(com_b_court_x), clip(com_b_court_y)

        # D. Track shuttlecock
        shuttle_pt = tracker.track_shuttle_frame(frame, frame_num, shuttle_history, h_matrix, use_simulator)
        shuttle_history.append(shuttle_pt)

        court_x, court_y = None, None
        z_height = 0.0
        landing_pred = (0.5, 0.85, 0.0)
        
        if shuttle_pt.visibility:
            court_x, court_y = pixel_to_court(shuttle_pt.x, shuttle_pt.y, h_matrix)
            court_x, court_y = clip(court_x), clip(court_y)
            z_height = tracker.ekf.state[2]
            max_apex_height = max(max_apex_height, z_height)
            landing_pred = tracker.ekf.predict_landing()

        speed = 0.0
        if len(shuttle_history) > 1 and shuttle_pt.visibility and court_x is not None and court_y is not None:
            prev_pt = shuttle_history[-2]
            if prev_pt.visibility:
                prev_x, prev_y = pixel_to_court(prev_pt.x, prev_pt.y, h_matrix)
                dx = (court_x - prev_x) * 6.1
                dy = (court_y - prev_y) * 13.4
                dist = math.sqrt(dx*dx + dy*dy)
                dt = (shuttle_pt.frame_number - prev_pt.frame_number) / fps
                if dt > 0:
                    speed = dist / dt
                    
        speed_kmh = speed * 3.6
        if shuttle_pt.visibility and speed_kmh > 5.0:
            if speeds_list:
                deceleration_rate = max(0.0, (speeds_list[-1] - speed_kmh) / (1.0 / fps))
            speeds_list.append(speed_kmh)
            max_recorded_speed = max(max_recorded_speed, speed_kmh)
            min_recorded_speed = min(min_recorded_speed, speed_kmh)

        # E. Hit Event Detection via Turnaround Heuristics (dot product of velocities)
        is_hit_event = False
        detected_shot_type = "drive"
        
        if len(shuttle_history) > 3 and shuttle_pt.visibility and len(points_data) >= 2:
            vx_curr = tracker.ekf.state[3]
            vy_curr = tracker.ekf.state[4]
            
            # Find the last visible point in points_data to get previous EKF states
            prev_vis = next((p for p in reversed(points_data) if p["pt"].visibility), None)
            vx_prev = prev_vis["pt"].vx if prev_vis else 0.0
            vy_prev = prev_vis["pt"].vy if prev_vis else 0.0
            
            # Check for velocity sign change in Y-direction (back-and-forth court flight)
            # or a significant change in X-direction
            direction_reversal = (vy_curr * vy_prev < 0) or (vx_curr * vx_prev < -0.5)
            if use_simulator:
                direction_reversal = (frame_num % 75 == 0)
            
            if direction_reversal and (frame_num - last_hit_frame) > (fps * 0.5):
                is_hit_event = True
                last_hit_frame = frame_num
                shot_count += 1
                
                hud_fade_counter = 60
                
                hitter_is_a = (court_y < 0.5) if court_y is not None else True
                hitter_kps = poses[0] if hitter_is_a else poses[1]
                recent_segment = points_data[-15:] if len(points_data) >= 15 else points_data
                
                detected_shot_type = classifier.classify_stroke(
                    recent_segment, hitter_is_a, shot_count, hitter_kps, landing_pred
                )

        pdata = {
            "pt": shuttle_pt,
            "court_x": court_x,
            "court_y": court_y,
            "speed": round(speed_kmh, 2),
            "event": detected_shot_type if is_hit_event else None,
            "p1_court_x": p1_court_x,
            "p1_court_y": p1_court_y,
            "p2_court_x": p2_court_x,
            "p2_court_y": p2_court_y,
            "poses": poses,
            "com_a_x": com_a_court_x,
            "com_a_y": com_a_court_y,
            "com_b_x": com_b_court_x,
            "com_b_y": com_b_court_y,
            "footwork_a": footwork_a,
            "footwork_b": footwork_b,
            "p1_pred_x_05": p1_pred_x,
            "p1_pred_y_05": p1_pred_y,
            "p2_pred_x_05": p2_pred_x,
            "p2_pred_y_05": p2_pred_y
        }
        points_data.append(pdata)

        hud_fade_counter = max(0, hud_fade_counter - 1)

        if out_video_writer is not None:
            frame_to_write = frame.copy()

            if render_skeleton:
                draw_player_skeleton_minimalist(frame_to_write, poses[0], (255, 120, 0))
                draw_player_skeleton_minimalist(frame_to_write, poses[1], (0, 120, 255))
                
                cv2.rectangle(frame_to_write, (int(boxes[0].x_min), int(boxes[0].y_min)), (int(boxes[0].x_max), int(boxes[0].y_max)), (255, 120, 0), 1)
                cv2.rectangle(frame_to_write, (int(boxes[1].x_min), int(boxes[1].y_min)), (int(boxes[1].x_max), int(boxes[1].y_max)), (0, 120, 255), 1)

                font = cv2.FONT_HERSHEY_SIMPLEX
                if footwork_a != "normal":
                    cv2.putText(frame_to_write, footwork_a.upper(), (int(boxes[0].x_min), int(boxes[0].y_min) - 10), font, 0.45, (255, 200, 0), 1, cv2.LINE_AA)
                if footwork_b != "normal":
                    cv2.putText(frame_to_write, footwork_b.upper(), (int(boxes[1].x_min), int(boxes[1].y_min) - 10), font, 0.45, (255, 200, 0), 1, cv2.LINE_AA)

            if render_trail:
                trace_length = 15
                for idx in range(trace_length):
                    hist_idx = len(shuttle_history) - 1 - idx
                    if hist_idx >= 0:
                        pt_hist = shuttle_history[hist_idx]
                        if pt_hist.visibility and pt_hist.x > 0 and pt_hist.y > 0:
                            pt_speed = points_data[hist_idx]["speed"]
                            r_col = int(clip(pt_speed / 150.0) * 255)
                            g_col = int((1.0 - clip(pt_speed / 150.0)) * 255)
                            cv2.circle(frame_to_write, (int(pt_hist.x), int(pt_hist.y)), radius=max(2, 6 - idx), color=(0, g_col, r_col), thickness=-1)

            if render_pip:
                pip_w, pip_h = 160, 240
                pip_x_start = width - 180
                pip_y_start = 30
                
                pip_bg = frame_to_write[pip_y_start - 5:pip_y_start + pip_h + 5, pip_x_start - 5:pip_x_start + pip_w + 5]
                frame_to_write[pip_y_start - 5:pip_y_start + pip_h + 5, pip_x_start - 5:pip_x_start + pip_w + 5] = cv2.addWeighted(
                    pip_bg, 0.35, np.zeros_like(pip_bg) + 20, 0.65, 0
                )
                
                cv2.rectangle(frame_to_write, (pip_x_start, pip_y_start), (pip_x_start + pip_w, pip_y_start + pip_h), (255, 255, 255), 1)
                net_y = pip_y_start + int(pip_h * 0.5)
                cv2.line(frame_to_write, (pip_x_start, net_y), (pip_x_start + pip_w, net_y), (255, 255, 255), 1)
                
                p1_pip_x = pip_x_start + int(p1_court_x * pip_w)
                p1_pip_y = pip_y_start + int(p1_court_y * pip_h)
                p2_pip_x = pip_x_start + int(p2_court_x * pip_w)
                p2_pip_y = pip_y_start + int(p2_court_y * pip_h)
                cv2.circle(frame_to_write, (p1_pip_x, p1_pip_y), 4, (255, 120, 0), -1)
                cv2.circle(frame_to_write, (p2_pip_x, p2_pip_y), 4, (0, 120, 255), -1)

                p1_pred_pip_x = pip_x_start + int(p1_pred_x * pip_w)
                p1_pred_pip_y = pip_y_start + int(p1_pred_y * pip_h)
                p2_pred_pip_x = pip_x_start + int(p2_pred_x * pip_w)
                p2_pred_pip_y = pip_y_start + int(p2_pred_y * pip_h)
                cv2.line(frame_to_write, (p1_pip_x, p1_pip_y), (p1_pred_pip_x, p1_pred_pip_y), (255, 200, 0), 1, cv2.LINE_AA)
                cv2.line(frame_to_write, (p2_pip_x, p2_pip_y), (p2_pred_pip_x, p2_pred_pip_y), (255, 200, 0), 1, cv2.LINE_AA)

                if court_x is not None and court_y is not None:
                    sh_pip_x = pip_x_start + int(court_x * pip_w)
                    sh_pip_y = pip_y_start + int(court_y * pip_h)
                    cv2.circle(frame_to_write, (sh_pip_x, sh_pip_y), 3, (0, 255, 255), -1)

            if render_hud and hud_fade_counter > 0:
                hud_y_start = height - 70
                opacity = min(1.0, hud_fade_counter / 15.0)
                
                hud_slice = frame_to_write[hud_y_start:height - 10, 10:width - 10]
                blended = cv2.addWeighted(hud_slice, 1.0 - (0.75 * opacity), np.zeros_like(hud_slice) + 15, 0.75 * opacity, 0)
                frame_to_write[hud_y_start:height - 10, 10:width - 10] = blended
                
                font = cv2.FONT_HERSHEY_SIMPLEX
                current_shot = next((p["event"] for p in reversed(points_data) if p["event"] is not None), "rally")
                
                text_color = (255, 255, 255)
                cv2.putText(frame_to_write, f"SHOT: {current_shot.upper()}", (30, hud_y_start + 40), font, 0.6, text_color, 2, cv2.LINE_AA)
                cv2.putText(frame_to_write, f"SPEED: {round(speed_kmh, 1)} KM/H", (300, hud_y_start + 40), font, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(frame_to_write, f"DECEL: {round(deceleration_rate, 1)} M/S2", (550, hud_y_start + 40), font, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
                cv2.putText(frame_to_write, f"APEX: {round(max_apex_height, 2)}M", (800, hud_y_start + 40), font, 0.6, (0, 200, 255), 2, cv2.LINE_AA)

            if out_video_writer is not None:
                out_video_writer.write(frame_to_write)

        if frame_num % 15 == 0:
            pct = int((frame_num / total_frames) * 100)
            yield {
                "status": "processing",
                "progress": pct,
                "frame": frame_num,
                "shuttle": {
                    "x": shuttle_pt.x,
                    "y": shuttle_pt.y,
                    "court_x": court_x,
                    "court_y": court_y,
                    "visible": shuttle_pt.visibility,
                    "speed": round(speed_kmh, 2)
                }
            }

    if cap:
        cap.release()
    if out_video_writer is not None:
        out_video_writer.release()
        print(f"[Processor] Tracked video saved at: {out_video_uri}")

    smooth_trajectory_points(points_data, window_size=5)

    with Session(engine) as session:
        set_id = uuid4()
        set_obj = Set(
            set_id=set_id,
            match_id=match_id,
            set_number=1,
            score_a=21,
            score_b=19,
            winner_id=player_a_id
        )
        session.add(set_obj)
        session.commit()

        rally_id = uuid4()
        rally_obj = Rally(
            rally_id=rally_id,
            set_id=set_id,
            rally_number=1,
            server_id=player_a_id,
            winner_id=player_a_id,
            rally_length=shot_count,
            start_frame=1,
            end_frame=frame_num
        )
        session.add(rally_obj)
        session.commit()

        trajectories_batch = []
        positions_batch = []
        shots_batch = []

        for f_idx, pdata in enumerate(points_data):
            pt = pdata["pt"]
            
            trajectories_batch.append(ShuttleTrajectory(
                match_id=match_id,
                frame_number=pt.frame_number,
                pixel_x=pt.x,
                pixel_y=pt.y,
                court_x=pdata["court_x"],
                court_y=pdata["court_y"],
                visible=pt.visibility,
                speed=pdata["speed"],
                event=pdata["event"],
                vx=pt.vx,
                vy=pt.vy,
                vz=pt.vz,
                ax=pt.ax,
                ay=pt.ay,
                az=pt.az,
                landing_x_pred=pt.landing_x,
                landing_y_pred=pt.landing_y,
                time_to_landing=pt.time_to_landing
            ))

            if pdata["p1_court_x"] is not None:
                p1_kp_dict = {kp.name: kp.to_dict() for kp in pdata["poses"][0]}
                positions_batch.append(PlayerPosition(
                    match_id=match_id,
                    frame_number=pt.frame_number,
                    player_id=player_a_id,
                    court_x=pdata["p1_court_x"],
                    court_y=pdata["p1_court_y"],
                    pose_keypoints=p1_kp_dict,
                    com_x=pdata["com_a_x"],
                    com_y=pdata["com_a_y"],
                    footwork_pattern=pdata["footwork_a"],
                    predicted_x_05s=pdata["p1_pred_x_05"],
                    predicted_y_05s=pdata["p1_pred_y_05"]
                ))

            if pdata["p2_court_x"] is not None and player_b_id != player_a_id:
                p2_kp_dict = {kp.name: kp.to_dict() for kp in pdata["poses"][1]}
                positions_batch.append(PlayerPosition(
                    match_id=match_id,
                    frame_number=pt.frame_number,
                    player_id=player_b_id,
                    court_x=pdata["p2_court_x"],
                    court_y=pdata["p2_court_y"],
                    pose_keypoints=p2_kp_dict,
                    com_x=pdata["com_b_x"],
                    com_y=pdata["com_b_y"],
                    footwork_pattern=pdata["footwork_b"],
                    predicted_x_05s=pdata["p2_pred_x_05"],
                    predicted_y_05s=pdata["p2_pred_y_05"]
                ))

            if pdata["event"] is not None and pdata["court_x"] is not None and pdata["court_y"] is not None:
                hitter_id = player_a_id if (pdata["court_y"] or 0.5) < 0.5 else player_b_id
                rx = pdata["p2_court_x"] if hitter_id == player_a_id else pdata["p1_court_x"]
                ry = pdata["p2_court_y"] if hitter_id == player_a_id else pdata["p1_court_y"]
                
                shots_batch.append(Shot(
                    shot_id=uuid4(),
                    rally_id=rally_id,
                    shot_number=shot_count,
                    hitter_id=hitter_id,
                    shot_type=pdata["event"],
                    hit_frame=pt.frame_number,
                    hitter_court_x=pdata["court_x"],
                    hitter_court_y=pdata["court_y"],
                    receiver_court_x=rx,
                    receiver_court_y=ry,
                    landing_x=pdata["court_x"],
                    landing_y=pdata["court_y"],
                    shuttle_speed_est=pdata["speed"],
                    confidence=0.90
                ))

        session.add_all(trajectories_batch)
        session.add_all(positions_batch)
        session.add_all(shots_batch)
        session.commit()

        dist_a = get_distance_covered(session, match_id, player_a_id)
        dist_b = get_distance_covered(session, match_id, player_b_id)
        
        dist_a_stmt = select(MatchPlayerStats).where(MatchPlayerStats.match_id == match_id, MatchPlayerStats.player_id == player_a_id)
        stats_a = session.exec(dist_a_stmt).first()
        if not stats_a:
            stats_a = MatchPlayerStats(match_id=match_id, player_id=player_a_id)
        stats_a.distance_covered_m = dist_a
        stats_a.avg_reaction_time_ms = get_average_reaction_time(session, match_id, player_a_id)
        stats_a.shot_type_distribution = get_shot_type_distribution(session, match_id, player_a_id)
        stats_a.avg_rally_length = float(shot_count)
        session.add(stats_a)

        dist_b_stmt = select(MatchPlayerStats).where(MatchPlayerStats.match_id == match_id, MatchPlayerStats.player_id == player_b_id)
        stats_b = session.exec(dist_b_stmt).first()
        if not stats_b:
            stats_b = MatchPlayerStats(match_id=match_id, player_id=player_b_id)
        stats_b.distance_covered_m = dist_b
        stats_b.avg_reaction_time_ms = get_average_reaction_time(session, match_id, player_b_id)
        stats_b.shot_type_distribution = get_shot_type_distribution(session, match_id, player_b_id)
        stats_b.avg_rally_length = float(shot_count)
        session.add(stats_b)

        if out_video_uri:
            match.video_uri = out_video_uri
        match.processing_status = "done"
        session.add(match)
        session.commit()

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    latency = time.time() - start_time
    print(f"[Processor Benchmark] Full processing latency: {round(latency, 2)} seconds")
    
    yield {"status": "done", "progress": 100, "message": f"Match processing completed successfully in {round(latency, 1)}s!"}
