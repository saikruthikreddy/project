FROM --platform=linux/amd64 python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements-azure.txt .
RUN pip install --default-timeout=360 --no-cache-dir -r requirements-azure.txt

# Download the spaCy model
RUN python -m spacy download en_core_web_sm

