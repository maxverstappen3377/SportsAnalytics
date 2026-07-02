# Use a secure, pre-configured image containing both Python and Node.js
FROM nikolaik/python-nodejs:python3.11-nodejs20-slim

WORKDIR /app

# Install comprehensive system dependencies for OpenCV, torch, and headless operation
# Including libgl1 which provides libGL.so.1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libglib2.0-0 \
    libgomp1 \
    libxcb1 \
    libxkbcommon0 \
    libxkbcommon-x11-0 \
    libxrender1 \
    libx11-6 \
    libxrandr2 \
    libxi6 \
    libxinerama1 \
    libfontconfig1 \
    fontconfig-config \
    libgl1 \
    libglx0 \
    libxdamage1 \
    libxfixes3 \
    libxxf86vm1 \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for headless and GPU-less operation
ENV OPENBLAS_NUM_THREADS=1
ENV OMP_NUM_THREADS=1
ENV CUDA_VISIBLE_DEVICES=""
ENV LIBGL_ALWAYS_INDIRECT=1
ENV QT_QPA_PLATFORM=offscreen
ENV DISPLAY=""
ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libGL.so.1

# 1. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Install Node dependencies
COPY package*.json ./
RUN npm ci

# 3. Copy the rest of your application code
COPY . .

# 4. Build your Next.js frontend production asset
RUN npm run build

# Expose Render's dynamic port
EXPOSE 10000

# 5. Start backend serving the application
CMD ["uvicorn", "src.pipeline.main:app", "--host", "0.0.0.0", "--port", "10000"]
