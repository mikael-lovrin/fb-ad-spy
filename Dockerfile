# ── FB Ad Spy — Production image ─────────────────────────────────────────────
#
# Base: official Playwright Python image (Ubuntu 22.04 + Chromium pre-installed)
# Adds: ffmpeg (for video audio extraction), Python deps, app code
#
# Build:  docker build -t fb-ad-spy .
# Stage1: docker run --env-file .env fb-ad-spy agents.count_agent --niche diabetes
# Full:   docker run --env-file .env fb-ad-spy pipeline --niche weight_loss

FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

# --- System dependencies ------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# --- Python dependencies ------------------------------------------------------
WORKDIR /app

COPY requirements.txt .
# Install without cache to keep image lean; stealth + psycopg2 included
RUN pip install --no-cache-dir -r requirements.txt

# Ensure the Playwright Chromium build matches the installed library version
RUN playwright install chromium --with-deps

# --- App code -----------------------------------------------------------------
COPY . .

# Create data directories (used by SQLite and temp media files)
RUN mkdir -p data/tmp data/media logs

# Default: show help so accidental runs don't start scraping
ENTRYPOINT ["python", "-m"]
CMD ["pipeline", "--help"]
