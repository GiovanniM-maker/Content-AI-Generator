FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (including Playwright/Chromium requirements)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libwayland-client0 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser
RUN playwright install chromium

# Copy application code
COPY . .

# Create data directory (for any local fallback — carousel images go to Supabase Storage)
RUN mkdir -p data static/video_output

# Expose port
EXPOSE 10000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/healthz')" || exit 1

# Start with gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "2", "--timeout", "120", "--keep-alive", "5"]
