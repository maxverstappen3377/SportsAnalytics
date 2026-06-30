import cv2
import os
from glob import glob

def images_to_video(image_folder, output_video, fps=30):
    images = sorted(glob(os.path.join(image_folder, "*.jpg")))
    if not images:
        raise ValueError("No JPG images found in folder")
    
    # Read first image to get dimensions
    frame = cv2.imread(images[0])
    h, w = frame.shape[:2]
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_video, fourcc, fps, (w, h))
    
    for img_path in images:
        frame = cv2.imread(img_path)
        out.write(frame)
    
    out.release()
    print(f"Video saved to {output_video}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python images_to_video.py <image_folder> <output_video>")
    else:
        images_to_video(sys.argv[1], sys.argv[2])
