# Giani AI Project Knowledge Base

A modern, modular Flask application for managing project knowledge and document processing with AI capabilities. This application provides intelligent document classification, processing, and search functionality powered by Google's Gemini AI.

## 🚀 Features

- **Document Processing**: Support for PDF, DOCX, PPTX, CSV, Excel, and image files
- **AI-Powered Classification**: Automatic document categorization using Gemini AI
- **Intelligent Chunking**: Adaptive document chunking for optimal processing
- **User Management**: Authentication and user-specific project organization
- **RESTful API**: Comprehensive API with standardized response format
- **Database Management**: SQLAlchemy ORM with SQLite and PostgreSQL support
- **Health Monitoring**: System health checks and monitoring endpoints

## 📁 Project Structure

```
projectknowledge/
├── main.py                    # Main application entry point
├── run.py                     # Development server runner
├── wsgi.py                    # Production WSGI entry point
├── requirements.txt           # Python dependencies
├── .env                       # Environment configuration
├── users.db                   # SQLite database (auto-generated)
│
├── giani_pkb/                 # Main application package
│   ├── __init__.py
│   │
│   ├── api/                   # API layer
│   │   ├── __init__.py
│   │   ├── auth_routes.py     # Authentication endpoints
│   │   ├── project_routes.py  # Project management endpoints
│   │   ├── document_routes.py # Document processing endpoints
│   │   ├── user_routes.py     # User management endpoints
│   │   └── health_routes.py   # Health check endpoints
│   │
│   ├── services/              # Business logic services
│   │   ├── __init__.py
│   │   ├── project_service.py # Project business logic
│   │   ├── document_upload_service.py # Document upload handling
│   │   └── classification_service.py # AI classification logic
│   │
│   ├── models/                # Data models
│   │   ├── __init__.py
│   │   └── database_models.py # SQLAlchemy ORM models
│   │
│   ├── database/              # Database layer
│   │   ├── __init__.py
│   │   ├── database_manager.py # Unified database operations
│   │   └── database_initialize.py # Database initialization
│   │
│   ├── preprocessing/         # Document processing
│   │   ├── __init__.py
│   │   ├── document_processor.py # Main orchestrator
│   │   ├── pdf_processor.py   # PDF processing
│   │   ├── docx_processor.py  # Word document processing
│   │   ├── pptx_processor.py  # PowerPoint processing
│   │   ├── csv_processor.py   # CSV/Excel processing
│   │   ├── image_processor.py # Image processing with OCR
│   │   └── chunking/          # Document chunking strategies
│   │       ├── __init__.py
│   │       ├── strategies.py  # Chunking algorithms
│   │       ├── token_counter.py # Token counting utilities
│   │       └── nlp_processor.py # NLP processing utilities
│   │
│   └── utils/                 # Utilities and helpers
│       ├── __init__.py
│       ├── config.py          # Configuration management
│       ├── auth_utils.py      # Authentication utilities
│       ├── response_utils.py  # API response formatting
│       ├── exceptions.py      # Custom exception classes
│       └── database.py        # Database connection utilities
│
└── temp_uploads/              # Temporary file storage
    └── data/                  # Processed document storage
        └── uploaded_documents/ # Organized by document type
```

## 🛠️ Technology Stack

- **Backend**: Flask 3.x with SQLAlchemy ORM
- **Database**: SQLite (development) / PostgreSQL (production)
- **AI/ML**: Google Gemini AI, LangChain, spaCy, Transformers
- **Document Processing**: PyMuPDF, python-docx, python-pptx, openpyxl
- **Authentication**: JWT tokens
- **API**: RESTful with standardized response format
- **Development**: pytest, black, flake8

## 📋 Prerequisites

- Python 3.8 or higher
- pip (Python package installer)
- Git
- Google Gemini API key (for AI features)
- Tesseract OCR (for image processing)

### System Dependencies

**macOS:**
```bash
# Install Tesseract OCR
brew install tesseract

# Install PostgreSQL (optional, for production)
brew install postgresql
```

**Ubuntu/Debian:**
```bash
# Install Tesseract OCR
sudo apt-get install tesseract-ocr

# Install PostgreSQL (optional, for production)
sudo apt-get install postgresql postgresql-contrib
```

**Windows:**
- Download Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki
- Download PostgreSQL from: https://www.postgresql.org/download/windows/

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone <repository-url>
cd projectknowledge
```

### 2. Set Up Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
# Install all dependencies
pip install -r requirements.txt

# Note: If you encounter PostgreSQL installation issues,
# the app will work with SQLite for development
```

### 4. Configure Environment

Create a `.env` file in the project root:

```env
FLASK_ENV=development
GEMINI_API_KEY=your_google_gemini_api_key_here
JWT_SECRET=your_jwt_secret_key_here
DATABASE_URL=sqlite:///./giani_ai.db
CORS_ORIGINS=http://localhost:3000,https://localhost:3000
LOG_LEVEL=INFO
```

**Get a Gemini API Key:**
1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key
3. Add it to your `.env` file

### 5. Initialize Database

```bash
# The database will be automatically initialized when you first run the app
# Or manually initialize:
python -c "from giani_pkb.database.database_initialize import DatabaseInitializer; DatabaseInitializer().initialize_database()"
```

### 6. Run the Application

**Development:**
```bash
python run.py
```

**Production:**
```bash
# Using WSGI
python wsgi.py

# Using Gunicorn
gunicorn wsgi:app
```

The application will be available at:
- **Local**: http://localhost:8000
- **API Documentation**: http://localhost:8000/api/v1
- **Health Check**: http://localhost:8000/api/v1/health/status

## 📚 API Documentation

### Base URL
```
http://localhost:8000
```

### Authentication
Most endpoints require JWT authentication. Include the token in the Authorization header:
```
Authorization: Bearer <your_jwt_token>
```

### Key Endpoints

#### Health Checks
- `GET /api/v1/health/status` - Basic health check
- `GET /api/v1/health/detailed` - Detailed system health
- `GET /api/v1/health/database` - Database health
- `GET /api/v1/health/system` - System resources

#### Authentication
- `POST /auth/register` - User registration
- `POST /auth/login` - User login
- `POST /auth/logout` - User logout

#### Projects
- `GET /api/v1/projects/` - Get user projects
- `POST /api/v1/projects/` - Create new project
- `GET /api/v1/projects/{id}` - Get project details
- `PUT /api/v1/projects/{id}` - Update project
- `DELETE /api/v1/projects/{id}` - Delete project

#### Documents
- `POST /api/v1/documents/upload` - Upload document
- `GET /api/v1/documents/` - Get project documents
- `POST /api/v1/documents/search` - Search documents
- `GET /api/v1/documents/{id}` - Get document details

### Response Format

All API responses follow a standardized format:

```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": {
    // Response data here
  },
  "error": null
}
```

Error responses:
```json
{
  "success": false,
  "message": "Error description",
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "details": "Additional error details"
  }
}
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=giani_pkb

# Run specific test file
pytest tests/test_auth.py
```

## 🔧 Development

### Code Style

The project uses:
- **Black** for code formatting
- **Flake8** for linting
- **Type hints** for better code documentation

```bash
# Format code
black giani_pkb/

# Check code style
flake8 giani_pkb/
```

### Adding New Features

1. **Create feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Follow the project structure:**
   - API routes go in `giani_pkb/api/`
   - Business logic goes in `giani_pkb/services/`
   - Models go in `giani_pkb/models/`
   - Utilities go in `giani_pkb/utils/`

3. **Add tests** for new functionality

4. **Update documentation** as needed

### Database Migrations

When modifying database models:

1. Update the model in `giani_pkb/models/database_models.py`
2. Run database initialization to apply changes:
   ```bash
   python -c "from giani_pkb.database.database_initialize import DatabaseInitializer; DatabaseInitializer().initialize_database()"
   ```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_ENV` | Flask environment | `development` |
| `GEMINI_API_KEY` | Google Gemini API key | Required |
| `JWT_SECRET` | JWT signing secret | `GIANIAI` |
| `DATABASE_URL` | Database connection string | `sqlite:///./giani_ai.db` |
| `CORS_ORIGINS` | Allowed CORS origins | `http://localhost:3000,https://localhost:3000` |
| `LOG_LEVEL` | Logging level | `INFO` |

## 🚀 Deployment

### Production Setup

1. **Use PostgreSQL:**
   ```env
   DATABASE_URL=postgresql://user:password@localhost/giani_ai
   ```

2. **Set secure JWT secret:**
   ```env
   JWT_SECRET=your_very_secure_random_secret
   ```

3. **Configure CORS for production domains:**
   ```env
   CORS_ORIGINS=https://yourdomain.com,https://api.yourdomain.com
   ```

4. **Use production WSGI server:**
   ```bash
   gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app
   ```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "wsgi:app"]
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add type hints to function signatures
- Write docstrings for all public functions
- Add tests for new functionality
- Update documentation for API changes
- Use meaningful commit messages

## 📝 License

[Add your license information here]

## 🆘 Support

For issues and questions:
1. Check the [Issues](https://github.com/your-repo/issues) page
2. Create a new issue with detailed information
3. Include error logs and steps to reproduce

## 🔄 Changelog

### Version 1.0.0
- Initial release
- Document processing and classification
- User authentication and project management
- RESTful API with standardized responses
- Health monitoring and system checks
