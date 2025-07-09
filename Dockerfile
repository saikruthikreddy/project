# Use Python 3.11 slim image
FROM --platform=linux/amd64 python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements-azure.txt .

# Install Python dependencies
RUN pip install --default-timeout=360 --no-cache-dir -r requirements-azure.txt

RUN python -m spacy download en_core_web_sm

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p temp_uploads/data/uploaded_documents

# Copy the entrypoint script into the container.
# This script will run database migrations before starting the app.
COPY ./entrypoint.sh /app/entrypoint.sh

# Make the entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Set the entrypoint script to be executed when the container starts
ENTRYPOINT ["/app/entrypoint.sh"]

# Expose port
EXPOSE 8000

# Use gunicorn as the WSGI server
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "300", "wsgi:app"]