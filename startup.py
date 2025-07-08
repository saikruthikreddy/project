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
