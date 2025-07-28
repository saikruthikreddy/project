# Use your custom base image which already has all dependencies installed
FROM gianidevacr.azurecr.io/giani-ai-base:latest

# Set the working directory (it's already /app in the base image, but it's good practice to be explicit)
WORKDIR /app

# Install SSH and configure it for Azure App Service
RUN apt-get update && apt-get install -y openssh-server \
    && echo "root:Docker!" | chpasswd \
    && echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config \
    && echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config \
    && mkdir -p /var/run/sshd \
    && rm -rf /var/lib/apt/lists/*

# Copy your application code. This is the only layer that will be rebuilt
# on most code changes, making the process very fast.
COPY . .

# Create necessary directories (if not already created in the base)
# This command is very fast and won't slow down the build.
RUN mkdir -p temp_uploads/data/uploaded_documents

# Copy SSH configuration for Azure
COPY sshd_config /etc/ssh/

# Copy and configure the entrypoint script
COPY ./entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Set the entrypoint for the container
ENTRYPOINT ["/app/entrypoint.sh"]

# Expose the port the app runs on
EXPOSE 8000 2222

# The command to start the Gunicorn server
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "300", "--log-level", "debug", "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]