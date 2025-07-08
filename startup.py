#!/usr/bin/env python3
"""
Startup script for Azure App Service deployment.
This file is used by Azure to start your Flask application.
"""
import os
import sys
from main import app

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# For Azure App Service, the application should be available as 'app'
if __name__ == "__main__":
    # Azure App Service will handle the server configuration
    # This is mainly for local testing
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
