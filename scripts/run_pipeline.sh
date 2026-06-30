#!/bin/bash
# Usage: ./run_pipeline.sh /path/to/image_folder [output_video] [model_path]

IMAGE_FOLDER=$1
VIDEO_NAME="temp_video.mp4"
OUTPUT_VIDEO=${2:-"tracked_output.mp4"}
MODEL=${3:-"model_best.pt"}

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PIPELINE_DIR="$SCRIPT_DIR/../src/pipeline"

echo "[Pipeline] Converting images in $IMAGE_FOLDER to temporary video..."
python "$PIPELINE_DIR/images_to_video.py" "$IMAGE_FOLDER" "$VIDEO_NAME"

echo "[Pipeline] Running TrackNet inference on $VIDEO_NAME..."
python "$PIPELINE_DIR/track_ball.py" "$VIDEO_NAME" "$OUTPUT_VIDEO" --model_path "$MODEL"

echo "[Pipeline] Cleaning up temporary video..."
rm "$VIDEO_NAME"

echo "[Pipeline] Complete! Output saved to $OUTPUT_VIDEO."
