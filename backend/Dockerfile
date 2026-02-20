FROM python:3.11-slim

# Build-time metadata
LABEL maintainer="UGIE Team" \
      description="Universal GitHub Intelligence Engine — API + Worker"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Non-root user for security
RUN useradd -m -u 1000 ugie && chown -R ugie:ugie /app
USER ugie

EXPOSE 8000

# Default command — override in docker-compose for worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
