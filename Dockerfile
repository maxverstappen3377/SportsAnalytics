# Use a secure, pre-configured image containing both Python and Node.js
FROM nikolaik/python-nodejs:python3.11-nodejs20-slim

WORKDIR /app

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
