#!/usr/bin/env python3
"""
Startup script for Azure App Service deployment.
This file is used by Azure to start your Flask application.
"""
import os
import sys
import logging

# Add current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    logger.info("Starting Giani AI Project Knowledge Base...")
    logger.info(f"Python path: {sys.path}")
    logger.info(f"Current directory: {os.getcwd()}")

    # Import the Flask app
    from main import app

    # Initialize database if needed
    try:
        from giani_pkb.database.database_initialize import DatabaseInitializer
        DatabaseInitializer().initialize_database()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.warning(f"Database initialization warning: {e}")

    logger.info("Application started successfully")

except Exception as e:
    logger.error(f"Failed to start application: {e}")
    raise

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)