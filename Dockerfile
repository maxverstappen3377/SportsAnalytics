# Use full Debian image with X11 support (not slim) to get all graphics libraries
FROM debian:bookworm

WORKDIR /app

# Install Node.js 20
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Python 3.11 with all system dependencies in one go
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3-pip \
    python3.11-dev \
    build-essential \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libglib2.0-0 \
    libgomp1 \
    libgl1 \
    libglx0 \
    libxkbcommon0 \
    libxkbcommon-x11-0 \
    libxrender1 \
    libx11-6 \
    libxrandr2 \
    libxi6 \
    libxinerama1 \
    libfontconfig1 \
    fontconfig-config \
    libxdamage1 \
    libxfixes3 \
    libxxf86vm1 \
    libxext6 \
    x11-common \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Set environment variables for headless operation
ENV PYTHONUNBUFFERED=1
ENV OPENBLAS_NUM_THREADS=1
ENV OMP_NUM_THREADS=1
ENV CUDA_VISIBLE_DEVICES=""
ENV LIBGL_ALWAYS_INDIRECT=1
ENV QT_QPA_PLATFORM=offscreen
ENV DISPLAY=""
ENV LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Node dependencies
COPY package*.json ./
RUN npm ci

# Copy application code
COPY . .

# Build Next.js frontend
RUN npm run build

# Expose Render's dynamic port
EXPOSE 10000

# Start backend serving the application
CMD ["uvicorn", "src.pipeline.main:app", "--host", "0.0.0.0", "--port", "10000"]
