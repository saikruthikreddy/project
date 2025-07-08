"""
Configuration settings for the Giani AI Project Knowledge Base application.
"""
import os
from dotenv import load_dotenv
from giani_pkb.utils.exceptions import ConfigurationError
from typing import Set

load_dotenv()

class Config:
    """Application configuration class."""

    # Database configuration
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'users.db')

    # JWT configuration
    JWT_SECRET = os.getenv('JWT_SECRET', 'GIANIAI')  # Move to environment variable in production
    JWT_ALGORITHM = 'HS256'

    # File upload configuration
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'temp_uploads')
    PROCESSED_FOLDER = os.getenv('PROCESSED_FOLDER', 'data/uploaded_documents')
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 50 * 1024 * 1024))  # 50MB default

    # Allowed file extensions
    ALLOWED_EXTENSIONS: Set[str] = {
        'pdf', 'docx', 'doc', 'txt', 'csv', 'xlsx', 'xls', 'pptx', 'ppt'
    }

    # Document types for folder structure
    DOCUMENT_TYPES = [
        'requirements_specifications',
        'technical_documentation',
        'business_strategic',
        'legal_compliance',
        'research_analysis',
        'marketing_communication',
        'project_management',
        'other'
    ]

    # Role/Purpose Categories
    ROLE_PURPOSE_CATEGORIES = [
        'Requirements & Specifications',
        'Technical Documentation',
        'Business & Strategic',
        'Legal & Compliance',
        'Research & Analysis',
        'Marketing & Communication',
        'Project Management',
        'Other'
    ]

    # API configuration
    API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5000')
    API_VERSION = 'v1'

    # CORS configuration
    CORS_ORIGINS = [
        "http://localhost:3000",
        "https://localhost:3000",
        "https://1e76-2404-7c00-44-5cfd-818a-9058-6e77-f38e.ngrok-free.app"
    ]

    # Logging configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    # AI Service configuration
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

    # Microsoft OAuth configuration
    MICROSOFT_CLIENT_ID = os.getenv('MICROSOFT_CLIENT_ID')
    MICROSOFT_CLIENT_SECRET = os.getenv('MICROSOFT_CLIENT_SECRET')
    MICROSOFT_TENANT_ID = os.getenv('MICROSOFT_TENANT_ID')

    @classmethod
    def ensure_directories_exist(cls):
        """Ensure all required directories exist."""
        import os

        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(cls.PROCESSED_FOLDER, exist_ok=True)

        for doc_type in cls.DOCUMENT_TYPES:
            os.makedirs(os.path.join(cls.PROCESSED_FOLDER, doc_type), exist_ok=True)

    @classmethod
    def allowed_file(cls, filename: str) -> bool:
        """Check if file extension is allowed."""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in cls.ALLOWED_EXTENSIONS

    @classmethod
    def get_category_folder(cls, category: str) -> str:
        """Get folder name for a category."""
        return category.lower().replace(' & ', '_').replace(' ', '_')

    @classmethod
    def validate_config(cls) -> bool:
        """Validate that all required configuration is present."""
        required_vars = [
            'GEMINI_API_KEY',
            'MICROSOFT_CLIENT_ID',
            'MICROSOFT_CLIENT_SECRET',
            'MICROSOFT_TENANT_ID'
        ]

        missing_vars = []
        for var in required_vars:
            if not getattr(cls, var):
                missing_vars.append(var)

        if missing_vars:
            print(f"Warning: Missing environment variables: {', '.join(missing_vars)}")
            print("Some features may not work correctly.")
            return False

        return True

# Global config instance
config = Config()

if not config.GEMINI_API_KEY:
    raise ConfigurationError("GEMINI_API_KEY environment variable not found or not set. Please ensure it is defined in your .env file or environment.")

GEMINI_PRO_MODEL = "gemini-1.5-pro"
GEMINI_FLASH_MODEL = "gemini-1.5-flash"
GEMINI_ADVANCED_MODEL = "gemini-2.0-pro"
GEMINI_FLASH_ALIAS = "gemini-2.0-flash"

# Module-level exports for backward compatibility
GEMINI_API_KEY = config.GEMINI_API_KEY

def get_api_key():
    """Returns the configured Gemini API key."""
    return config.GEMINI_API_KEY

def get_default_model():
    """Returns the default Gemini model name."""
    return GEMINI_FLASH_MODEL

def get_pro_model():
    """Returns the Gemini Pro model name."""
    return GEMINI_PRO_MODEL
