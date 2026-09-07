# Base image with Python 3.11 slim
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for Pillow, networking, and optional graphics libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source files
COPY . .

# Ensure static uploads directory exists
RUN mkdir -p static/uploads/crops

# Expose default port
EXPOSE 8000

# Default Environment Variables
ENV HOST=0.0.0.0
ENV PORT=8000
ENV JWT_SECRET=agridirect_live_production_secret_key_2026_super_secure
ENV DEMO_MODE=true

# Launch Uvicorn application server binding dynamically to $PORT provided by Railway
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
