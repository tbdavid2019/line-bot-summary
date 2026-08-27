# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install system dependencies (ffmpeg, curl, unzip, deno JS runtime for yt-dlp challenges)
# Dynamically detects CPU architecture (x86_64 or aarch64/arm64) for multi-platform compatibility
RUN apt-get update && apt-get install -y ffmpeg curl unzip && rm -rf /var/lib/apt/lists/* \
    && ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
         DENO_ARCH="aarch64-unknown-linux-gnu"; \
       else \
         DENO_ARCH="x86_64-unknown-linux-gnu"; \
       fi \
    && curl -fsSL "https://github.com/denoland/deno/releases/latest/download/deno-${DENO_ARCH}.zip" -o /tmp/deno.zip \
    && unzip -o /tmp/deno.zip -d /usr/local/bin \
    && rm -f /tmp/deno.zip \
    && chmod +x /usr/local/bin/deno

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN python3 -m pip install -U --pre "yt-dlp[default]"

RUN touch /app/cookies.txt
# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define environment variable in key=value format
ENV NAME=World

# Run high-concurrency async FastAPI with Gunicorn + UvicornWorker
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-k", "uvicorn.workers.UvicornWorker", "--workers", "4", "--timeout", "300", "--max-requests", "1000", "--max-requests-jitter", "100", "app:app"]
