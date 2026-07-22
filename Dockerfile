# Multi-stage image for Audiobook Forge.
#
# Python is pinned to 3.10 because the piper-tts wheels target <=3.10. The image
# bundles ffmpeg + espeak-ng so no host dependencies are required.

FROM python:3.10-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime system dependencies: ffmpeg (audio), espeak-ng (Piper phonemization),
# unrar for optional RAR support, and libsndfile for audio I/O.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        espeak-ng \
        libsndfile1 \
        unrar-free \
        p7zip-full \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml requirements.txt ./
RUN pip install -r requirements.txt

# Install the application.
COPY . .
RUN pip install -e .

# Non-root user for safety.
RUN useradd --create-home --uid 1000 forge \
    && mkdir -p /app/.work /app/.out /app/.cache /app/.queue \
    && chown -R forge:forge /app
USER forge

# Default: run the Telegram bot. Override the command to run a worker/convert.
ENTRYPOINT ["audiobook-forge"]
CMD ["bot"]
