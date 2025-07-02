#  main_ppt_addin.py (Entry Point)
# ================================
from flask import Flask
from flask_cors import CORS
from api_endpoint.ppt_addin_controller import ppt_bp
from dotenv import load_dotenv
import os

# Load env vars from both .env and config/secrets.env
load_dotenv(".env")
load_dotenv("config/secrets.env")

def create_app():
    app = Flask(__name__)
    
    # Enable CORS for frontend communication
    CORS(app)
    
    # Register blueprint with API prefix
    app.register_blueprint(ppt_bp, url_prefix="/api")
    
    return app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
