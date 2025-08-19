# Giani AI Project Knowledge Base

A modern, modular Flask application for managing project knowledge and document processing with AI capabilities. This application provides intelligent document classification, processing, and search functionality powered by Google's Gemini AI, deployed on Azure infrastructure.

## 🚀 Features

- **Document Processing**: Support for PDF, DOCX, PPTX, CSV, Excel, and image files with OCR
- **AI-Powered Classification**: Automatic document categorization using Gemini AI
- **Intelligent Chunking**: Adaptive document chunking for optimal processing
- **RAG (Retrieval-Augmented Generation)**: Advanced document search and retrieval using LlamaIndex
- **User Management**: Authentication with Microsoft OAuth and JWT tokens
- **Project Management**: User-specific project organization and collaboration
- **PowerPoint Add-in Integration**: AI-powered slide title generation, content improvement, and structure optimization
- **Onboarding Guide Generation**: Automated project onboarding guide creation
- **Analytics & Monitoring**: Comprehensive user activity tracking and system health monitoring
- **RESTful API**: Comprehensive API with standardized response format
- **Database Management**: SQLAlchemy ORM with PostgreSQL support and Alembic migrations
- **Health Monitoring**: System health checks and monitoring endpoints
- **Multi-Cloud Storage**: Azure Blob Storage with local storage fallback

## 🏗️ Architecture Overview

### Azure Infrastructure
- **Web App**: `giani-dev-wa` - Flask application deployed on Azure Web App Service
- **Azure Functions**: `giani-dev-workers` - Serverless document processing and onboarding guide generation
- **Database**: `giani-dev-db-server` - PostgreSQL database on Azure Database for PostgreSQL
- **Storage**: `gianidevstorage` - Azure Blob Storage for document storage
- **Service Bus**: `giani-dev-servicebus` - Message queuing for async document processing
- **Resource Group**: `giani-dev-rg` - All resources organized under this resource group

### System Components
- **Flask Web Application**: Main API server with authentication, project management, and document processing
- **Azure Functions**: Background workers for document processing and onboarding guide generation
- **RAG Engine**: LlamaIndex-based retrieval and query system for intelligent document search
- **Analytics Middleware**: Automatic tracking of user activities and API usage
- **Storage Factory**: Dynamic storage service selection (Azure Blob vs Local)

## 📁 Project Structure

```
projectknowledge/
├── main.py                    # Main application entry point
├── run.py                     # Development server runner
├── wsgi.py                    # Production WSGI entry point
├── manage.py                  # Database management CLI tool
├── requirements.txt           # Python dependencies
├── requirements-azure.txt     # Azure-specific dependencies
├── Dockerfile                 # Main application container
├── base.Dockerfile            # Base image with dependencies
├── entrypoint.sh              # Container startup script
├── alembic.ini               # Database migration configuration
├── migrations/                # Database migration files
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── API_ROUTES_ORGANIZATION.md # API routes documentation
│
├── azure_functions/           # Azure Functions for background processing
│   ├── DocumentProcessor/     # Document processing function
│   │   ├── __init__.py
│   │   └── function.json
│   ├── OnboardingProcessor/   # Onboarding guide generation function
│   │   ├── __init__.py
│   │   └── function.json
│   ├── host.json              # Azure Functions host configuration
│   ├── local.settings.example.json
│   ├── requirements.txt       # Function-specific dependencies
│   ├── Dockerfile             # Functions container
│   ├── .dockerignore          # Docker ignore file
│   ├── .funcignore            # Functions ignore file
│   │
│   ├── services/              # Business logic services
│   │   ├── document_upload_service.py # Document upload handling
│   │   ├── blob_storage_service.py # Azure Blob Storage service
│   │   ├── storage_service_base.py # Common storage service interface
│   │   ├── service_bus_sender.py # Azure Service Bus integration
│   │   ├── onboarding_guide_service.py # Onboarding guide generation
│   │   ├── summarization.py # Document summarization logic
│   │   ├── metadata_manager.py # Metadata management
│   │   └── classification.py # AI classification logic
│   │
│   ├── utils/                 # Utilities and helpers
│   │   ├── config.py          # Configuration management
│   │   ├── database.py        # Database connection utilities
│   │   ├── gemini_client.py   # Gemini AI client
│   │   ├── prompt_loader.py   # Prompt loading utilities
│   │   ├── prompt_generators.py # Prompt generation helpers
│   │   ├── api_tracker.py     # API usage tracking
│   │   ├── summarization.py   # Summarization utilities
│   │   ├── classification_utils.py # Classification helpers
│   │   ├── classification.py  # Classification logic
│   │   ├── constants.py       # Project constants
│   │   └── exceptions.py      # Custom exception classes
│   │
│   ├── models/                # Data models
│   │   ├── database_models.py # SQLAlchemy ORM models
│   │   └── document.py        # Document model helpers
│   │
│   ├── database/              # Database layer
│   │   └── database_manager.py # Database operations and management
│   │
│   ├── preprocessing/         # Document processing
│   │   ├── document_processor.py # Main orchestrator
│   │   ├── pdf_processor.py   # PDF processing
│   │   ├── docx_processor.py  # Word document processing
│   │   ├── pptx_processor.py  # PowerPoint processing
│   │   ├── csv_processor.py   # CSV/Excel processing
│   │   ├── image_processor.py # Image processing with OCR
│   │   └── chunking/          # Document chunking strategies
│   │       ├── strategies.py  # Chunking algorithms
│   │       ├── token_counter.py # Token counting utilities
│   │       ├── nlp_processor.py # NLP processing utilities
│   │       └── models.py      # Chunking models
│   │
│   ├── prompts/               # Prompt templates
│   │   ├── __init__.py
│   │   ├── summarization_group_a_prompt.txt
│   │   ├── summarization_group_b_prompt.txt
│   │   ├── summarization_group_c_prompt.txt
│   │   ├── summarization_group_d_prompt.txt
│   │   ├── csv_analysis_prompt.txt
│   │   ├── file_classification_prompt.txt
│   │   ├── mission_and_approach_prompt.txt
│   │   ├── priority_reading_list_prompt.txt
│   │   ├── strategic_intelligence_readout_prompt.txt
│   │   ├── knowledge_base_faq_prompt.txt
│   │   └── ppt_addin_prompts/ # PowerPoint add-in specific prompts
│   │       ├── first_slide_prompt.txt
│   │       ├── title_generation_prompt.txt
│   │       ├── title_refine_prompt.txt
│   │       ├── title_regeneration_prompt.txt
│   │       ├── Parallelize_content_prompt.txt
│   │       ├── slide_review_prompt.txt
│   │       ├── slide_structure_prompt.txt
│   │       └── Slide_structure_regenerate_prompt.txt
│   │
│   ├── data/                  # Data storage
│   ├── logs/                  # Function execution logs
│   └── venv/                  # Python virtual environment
│
├── giani_pkb/                 # Main application package
│   ├── __init__.py
│   │
│   ├── api/                   # API layer
│   │   ├── __init__.py
│   │   ├── auth_routes.py     # Authentication endpoints
│   │   ├── project_routes.py  # Project management endpoints
│   │   ├── user_routes.py     # User management endpoints
│   │   ├── health_routes.py   # Health check endpoints
│   │   ├── ppt_addin_routes.py # PowerPoint add-in endpoints
│   │   ├── analytics_routes.py # Analytics and monitoring endpoints
│   │   └── onboarding_guide_routes.py # Onboarding guide endpoints
│   │
│   ├── services/              # Business logic services
│   │   ├── __init__.py
│   │   ├── project_service.py # Project business logic
│   │   ├── document_upload_service.py # Document upload handling
│   │   ├── ppt_title_service.py # PPT title generation
│   │   ├── ppt_title_refine_service.py # PPT title refinement
│   │   ├── ppt_improve_selected_text_service.py # PPT text improvement
│   │   ├── ppt_parallelize_content_service.py # PPT content parallelization
│   │   ├── ppt_slide_structure.py # PPT slide structure
│   │   ├── slide_review_service.py # Slide review
│   │   ├── summarization.py # Summarization logic
│   │   ├── metadata_manager.py # Metadata management
│   │   ├── classification.py # AI classification logic
│   │   ├── analytics_service.py # User activity analytics
│   │   ├── onboarding_guide_service.py # Onboarding guide generation
│   │   ├── storage_factory.py # Dynamic storage service selection
│   │   ├── blob_storage_service.py # Azure Blob Storage service
│   │   ├── local_storage_service.py # Local storage service
│   │   └── rag/               # RAG (Retrieval-Augmented Generation) services
│   │       ├── query_engine.py # Query engine configuration
│   │       ├── retriever_service.py # Document retrieval service
│   │       ├── index_builder.py # Vector index building
│   │       ├── embed_chunks.py # Document chunk embedding
│   │       ├── node_converter.py # Document node conversion
│   │       ├── citation_formatter.py # Citation formatting
│   │       └── csv_index_builder.py # CSV-specific indexing
│   │
│   ├── models/                # Data models
│   │   ├── __init__.py
│   │   ├── database_models.py # SQLAlchemy ORM models
│   │   └── document.py        # Document model helpers
│   │
│   ├── database/              # Database layer
│   │   ├── __init__.py
│   │   ├── database_manager.py # Unified database operations
│   │   ├── database_initialize.py # Database initialization
│   │   └── database_migration.py # Database migration logic
│   │
│   ├── middleware/            # Application middleware
│   │   ├── __init__.py
│   │   ├── auth_session_middleware.py # Authentication session management
│   │   └── analytics_middleware.py # Automatic analytics tracking
│   │
│   ├── preprocessing/         # Document processing
│   │   ├── __init__.py
│   │   ├── document_processor.py # Main orchestrator
│   │   ├── pdf_processor.py   # PDF processing
│   │   ├── docx_processor.py  # Word document processing
│   │   ├── pptx_processor.py  # PowerPoint processing
│   │   ├── csv_processor.py   # CSV/Excel processing
│   │   ├── image_processor.py # Image processing with OCR
│   │   ├── test_chunking_strategies.py # Chunking tests
│   │   ├── test_processing.py # Processing tests
│   │   └── chunking/          # Document chunking strategies
│   │       ├── __init__.py
│   │       ├── strategies.py  # Chunking algorithms
│   │       ├── token_counter.py # Token counting utilities
│   │       ├── nlp_processor.py # NLP processing utilities
│   │       └── models.py      # Chunking models
│   │
│   ├── utils/                 # Utilities and helpers
│   │   ├── __init__.py
│   │   ├── config.py          # Configuration management
│   │   ├── auth_utils.py      # Authentication utilities
│   │   ├── response_utils.py  # API response formatting
│   │   ├── exceptions.py      # Custom exception classes
│   │   ├── database.py        # Database connection utilities
│   │   ├── database_utils.py  # Database utility functions
│   │   ├── constants.py       # Project constants
│   │   ├── prompt_generators.py # Prompt generation helpers
│   │   ├── prompt_loader.py   # Prompt loading utilities
│   │   ├── gemini_client.py   # Gemini AI client
│   │   ├── api_tracker.py     # API usage tracking
│   │   └── classification_utils.py # Classification helpers
│   │
│   ├── ui/                    # UI applications
│   │   ├── __init__.py
│   │   ├── file_upload_app.py # File upload UI
│   │   └── summarization_app.py # Summarization UI
│   │
│   └── prompts/               # Prompt templates
│       ├── __init__.py
│       ├── summarization_group_a_prompt.txt
│       ├── summarization_group_b_prompt.txt
│       ├── summarization_group_c_prompt.txt
│       ├── summarization_group_d_prompt.txt
│       ├── csv_analysis_prompt.txt
│       ├── file_classification_prompt.txt
│       ├── mission_and_approach_prompt.txt
│       ├── priority_reading_list_prompt.txt
│       ├── strategic_intelligence_readout_prompt.txt
│       └── ppt_addin_prompts/ # PowerPoint add-in specific prompts
│           ├── first_slide_prompt.txt
│           ├── title_generation_prompt.txt
│           ├── title_refine_prompt.txt
│           ├── title_regeneration_prompt.txt
│           ├── Parallelize_content_prompt.txt
│           ├── slide_review_prompt.txt
│           ├── slide_structure_prompt.txt
│           ├── Slide_structure_regenerate_prompt.txt
│           └── improveSelectedText_prompt.txt
```

## 🛠️ Technology Stack

### Backend & Framework
- **Web Framework**: Flask 3.x with SQLAlchemy ORM
- **Database**: PostgreSQL (Azure Database for PostgreSQL)
- **Migrations**: Alembic for database schema management
- **Authentication**: JWT tokens with Microsoft OAuth integration

### AI/ML & Language Processing
- **AI Models**: Google Gemini AI (1.5 Pro, 1.5 Flash, 2.0 Pro)
- **RAG Engine**: LlamaIndex for document retrieval and querying
- **Language Processing**: LangChain, spaCy, Transformers
- **Document Processing**: PyMuPDF, python-docx, python-pptx, openpyxl
- **OCR**: Tesseract for image text extraction

### Cloud & Infrastructure
- **Cloud Platform**: Microsoft Azure
- **Containerization**: Docker with multi-stage builds
- **Serverless**: Azure Functions for background processing
- **Storage**: Azure Blob Storage with local fallback
- **Message Queuing**: Azure Service Bus
- **Web Hosting**: Azure Web App Service

### Development & Testing
- **Code Quality**: pytest, black, flake8
- **Type Hints**: Full Python type annotation support
- **Documentation**: Comprehensive API documentation

## 📋 Prerequisites

- Python 3.11 or higher
- pip (Python package installer)
- Git
- Docker (for containerized deployment)
- Azure CLI (for Azure deployment)

### Required API Keys & Configuration
- **Google Gemini API Key** (required for AI features)
- **Microsoft OAuth Credentials** (for authentication)
- **Azure Service Principal** (for Azure resource management)

### System Dependencies

**macOS:**
```bash
# Install Tesseract OCR
brew install tesseract

# Install PostgreSQL (optional, for local development)
brew install postgresql
```

**Ubuntu/Debian:**
```bash
# Install Tesseract OCR
sudo apt-get install tesseract-ocr

# Install PostgreSQL (optional, for local development)
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
# For local development
pip install -r requirements.txt

# For Azure deployment
pip install -r requirements-azure.txt
```

### 4. Configure Environment

Create a `.env` file in the project root:

```env
# Flask Configuration
FLASK_ENV=development
JWT_SECRET=your_jwt_secret_key_here
CORS_ORIGINS=http://localhost:3000,https://localhost:3000
LOG_LEVEL=INFO

# AI Services
GEMINI_API_KEY=your_google_gemini_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here

# Microsoft OAuth
MICROSOFT_CLIENT_ID=your_microsoft_client_id
MICROSOFT_CLIENT_SECRET=your_microsoft_client_secret
MICROSOFT_TENANT_ID=your_microsoft_tenant_id

# Database
DATABASE_URL=postgresql://user:password@localhost/giani_ai

# Azure Services (for production)
STORAGE_ACCOUNT_URL=your_azure_storage_account_url
STORAGE_CONNECTION_STRING=your_azure_storage_connection_string
SERVICE_BUS_CONNECTION_STRING=your_azure_service_bus_connection_string
DOCUMENT_PROCESSING_QUEUE=your_document_processing_queue_name
ONBOARDING_PROCESSING_QUEUE=your_onboarding_processing_queue_name

# Storage Configuration
USE_BLOB_STORAGE=true
TEMP_DOCUMENTS_CONTAINER=temp-documents
DOCUMENTS_CONTAINER=documents
ONBOARDINGS_CONTAINER=onboardings
```

**Get API Keys:**

1. **Google Gemini**: Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. **Microsoft OAuth**: Configure in [Azure Portal](https://portal.azure.com)
3. **Azure Services**: Use Azure CLI or Portal to get connection strings

### 5. Initialize Database

```bash
# Initialize database schema
python manage.py init

# Apply any existing migrations
python manage.py apply
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

**Docker:**
```bash
# Build and run
docker build -t giani-ai .
docker run -p 8000:8000 giani-ai
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

#### PowerPoint Add-in
- `POST /api/v1/ppt/suggest-titles` - Generate slide titles
- `POST /api/v1/ppt/refine-title` - Refine slide titles
- `POST /api/v1/ppt/generate-slide-structure` - Generate slide structure
- `POST /api/v1/ppt/refine-selected-text` - Improve selected text
- `POST /api/v1/ppt/parallelize-content` - Parallelize content
- `POST /api/v1/ppt/review-slide` - Review slide content

#### Onboarding Guides
- `GET /api/v1/projects/{id}/onboarding-guide` - Generate project onboarding guide

#### Analytics
- `GET /api/v1/analytics/user/summary` - User activity summary
- `GET /api/v1/analytics/user/activities` - Detailed user activities
- `GET /api/v1/analytics/project/{id}/summary` - Project activity summary
- `GET /api/v1/analytics/system/overview` - System overview

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

# Run tests with verbose output
pytest -v
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

### Database Migrations
When modifying database models:

1. Update the model in `giani_pkb/models/database_models.py`
2. Create a new migration:
   ```bash
   python manage.py create-migration "Description of changes"
   ```
3. Apply the migration:
   ```bash
   python manage.py apply
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

## 🚀 Azure Deployment

### Prerequisites
- Azure subscription
- Azure CLI installed and configured
- Docker registry (Azure Container Registry recommended)

### Deployment Steps

1. **Build and Push Docker Images:**
   ```bash
   # Build base image
   docker build -f base.Dockerfile -t gianidevacr.azurecr.io/giani-ai-base:latest .

   # Build main application
   docker build -t gianidevacr.azurecr.io/giani-ai:latest .

   # Push to Azure Container Registry
   az acr login --name gianidevacr
   docker push gianidevacr.azurecr.io/giani-ai:latest
   ```

2. **Deploy Azure Functions:**
   ```bash
   cd azure_functions
   func azure functionapp publish giani-dev-workers
   ```

3. **Configure Environment Variables:**
   Set all required environment variables in Azure Web App and Function App configurations.

4. **Deploy Web Application:**
   ```bash
   # Deploy to Azure Web App
   az webapp deployment source config-zip --resource-group giani-dev-rg --name giani-dev-wa --src deployment.zip
   ```

### Environment Variables for Azure

| Variable | Description | Required |
|----------|-------------|----------|
| `GEMINI_API_KEY` | Google Gemini API key | Yes |
| `MICROSOFT_CLIENT_ID` | Microsoft OAuth client ID | Yes |
| `MICROSOFT_CLIENT_SECRET` | Microsoft OAuth client secret | Yes |
| `MICROSOFT_TENANT_ID` | Microsoft tenant ID | Yes |
| `STORAGE_CONNECTION_STRING` | Azure Blob Storage connection string | Yes |
| `SERVICE_BUS_CONNECTION_STRING` | Azure Service Bus connection string | Yes |
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `USE_BLOB_STORAGE` | Enable Azure Blob Storage | Yes (true) |

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

### Version 2.0.0 (Current)
- Azure cloud deployment architecture
- Azure Functions for background processing
- RAG engine with LlamaIndex integration
- Analytics and monitoring system
- PowerPoint add-in integration
- Onboarding guide generation
- Multi-cloud storage support
- Comprehensive API endpoints

### Version 1.0.0
- Initial release
- Document processing and classification
- User authentication and project management
- RESTful API with standardized responses
- Health monitoring and system checks
