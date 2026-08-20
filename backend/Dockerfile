FROM python:3.12-slim

# Install ffmpeg (required by yt-dlp for merging/format conversion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp and Python web framework dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app

# Copy app code (dev overrides with a volume mount for hot-reload)
COPY app/ /app/app/

EXPOSE 8000

# Default command (dev uses --reload via docker-compose override)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]