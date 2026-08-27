# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install system dependencies (ffmpeg)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN python3 -m pip install -U --pre "yt-dlp[default]"

COPY cookies.txt /app/cookies.txt
# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define environment variable in key=value format
ENV NAME=World

# Run high-concurrency async FastAPI with Gunicorn + UvicornWorker
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-k", "uvicorn.workers.UvicornWorker", "--workers", "4", "--timeout", "300", "--max-requests", "1000", "--max-requests-jitter", "100", "app:app"]
