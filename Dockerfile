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

# Make entrypoint script executable
RUN chmod +x start.sh

# Expose default port (Railway overrides this with $PORT at runtime)
EXPOSE 8000

# Environment defaults
# CRITICAL: HOST must be 0.0.0.0 — Railway's reverse proxy routes via the container network,
#           not localhost. PORT is always injected by Railway at runtime.
ENV HOST=0.0.0.0
ENV PORT=8000
ENV JWT_SECRET=agridirect_live_production_secret_key_2026_super_secure
ENV DEMO_MODE=true

# Use start.sh so Railway's $PORT is correctly passed to uvicorn at runtime
CMD ["./start.sh"]
