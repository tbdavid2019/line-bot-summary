# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt
RUN python3 -m pip install -U --pre "yt-dlp[default]"

COPY cookies.txt /app/cookies.txt
# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define environment variable in key=value format
ENV NAME=World

# Run app.py when the container launches
CMD ["gunicorn", "-b", "0.0.0.0:5000", "--timeout", "300", "--workers", "1", "--worker-class", "sync", "--max-requests", "100", "--max-requests-jitter", "10", "app:app"]
