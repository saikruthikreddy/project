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
├── main.py                       # Flask app factory, CORS, middleware, blueprints
├── run.py                        # Dev server (http://localhost:8000)
├── wsgi.py                       # WSGI entry (production)
├── manage.py                     # DB CLI (alembic wrappers: status, apply, create-migration)
├── requirements.txt              # Core dependencies
├── requirements-azure.txt        # Azure/production dependencies
├── Dockerfile                    # App container build
├── base.Dockerfile               # Base image build stage
├── entrypoint.sh                 # Container entrypoint script
├── alembic.ini                   # Alembic configuration
├── migrations/                   # Alembic migrations
│   ├── env.py                    # Alembic environment & DB connection setup
│   ├── script.py.mako            # Migration file template
│   └── versions/
│       ├── 2025_07_28_1748-..._initial_database_schema.py          # Initial schema
│       └── 2025_08_04_0828-..._add_source_column_to_documentsummary_.py # Adds column
├── API_ROUTES_ORGANIZATION.md    # API routes overview
│
├── azure_functions/              # Azure Functions workers
│   ├── DocumentProcessor/
│   │   ├── __init__.py           # Function entry for document processing
│   │   └── function.json         # Trigger/bindings configuration
│   ├── OnboardingProcessor/
│   │   ├── __init__.py           # Function entry for onboarding processing
│   │   └── function.json         # Trigger/bindings configuration
│   ├── database/
│   │   └── database_manager.py   # DB utilities for functions runtime
│   ├── models/
│   │   ├── database_models.py    # ORM models (functions scope)
│   │   └── document.py           # Document helpers (functions scope)
│   ├── preprocessing/
│   │   ├── csv_processor.py      # CSV/Excel preprocessing
│   │   ├── document_processor.py # Orchestrates preprocessing & metadata
│   │   ├── docx_processor.py     # Word preprocessing
│   │   ├── image_processor.py    # OCR for images
│   │   ├── pdf_processor.py      # PDF extraction
│   │   ├── pptx_processor.py     # PowerPoint preprocessing
│   │   └── chunking/
│   │       ├── __init__.py       # Package marker
│   │       ├── chunking_config.py# Chunking defaults/config
│   │       ├── models.py         # Chunk data structures
│   │       ├── nlp_processor.py  # NLP utilities
│   │       ├── strategies.py     # Chunking strategies
│   │       ├── token_counter.py  # Token counting helpers
│   │       └── validators.py     # Chunking validators
│   ├── prompts/
│   │   ├── *.txt                 # Prompt templates
│   │   └── ppt_addin_prompts/*.txt # PPT add-in prompts
│   ├── services/
│   │   ├── blob_storage_service.py    # Azure Blob client
│   │   ├── classification.py          # AI classification service
│   │   ├── document_upload_service.py # Upload handling
│   │   ├── metadata_manager.py        # Metadata extraction/management
│   │   ├── onboarding_guide_service.py# Onboarding guide generation
│   │   ├── rag/
│   │   │   ├── answer_verifier.py     # Answer verification
│   │   │   ├── citation_formatter.py  # Citation formatting
│   │   │   ├── config_loader.py       # RAG config loader
│   │   │   ├── csv_index_builder.py   # CSV indexing
│   │   │   ├── embed_chunk.py         # Chunk embedding
│   │   │   ├── fusion.py              # Fusion search
│   │   │   ├── index_builder.py       # Index construction
│   │   │   ├── intent_router.py       # Intent routing
│   │   │   ├── llm_service.py         # LLM wrapper
│   │   │   ├── node_converter.py      # Doc→node conversion
│   │   │   ├── planner.py             # Query planning
│   │   │   ├── post_retrieval.py      # Post-retrieval steps
│   │   │   ├── query_engine.py        # Query engine (functions)
│   │   │   ├── query_executor.py      # RAG execution
│   │   │   ├── query_orchestrator.py  # High-level orchestrator
│   │   │   ├── reranker.py            # Result re-ranking
│   │   │   └── retrieval_service.py   # Retriever setup/search
│   │   ├── service_bus_sender.py      # Azure Service Bus producer
│   │   ├── storage_service_base.py    # Storage interface
│   │   └── summarization.py           # Summarization helpers
│   ├── utils/
│   │   ├── api_tracker.py       # API usage tracking
│   │   ├── auth_utils.py        # Token/cookie helpers
│   │   ├── classification.py    # Classification helpers
│   │   ├── classification_utils.py # Classification utilities
│   │   ├── config.py            # Settings loader
│   │   ├── constants.py         # Constants
│   │   ├── database.py          # DB connections
│   │   ├── exceptions.py        # Custom exceptions
│   │   ├── gemini_client.py     # Gemini API client
│   │   ├── logging.py           # Functions logging setup
│   │   ├── prompt_generators.py # Dynamic prompt generation
│   │   ├── prompt_loader.py     # Loads prompt templates
│   │   └── summarization.py     # Summarization utilities
│   ├── host.json                # Functions host config
│   ├── local.settings.example.json # Local dev settings example
│   ├── Dockerfile               # Functions container build
│   └── data/, logs/, venv/      # Runtime data, logs, venv (local)
│
├── giani_pkb/                    # Main Flask application
│   ├── api/
│   │   ├── analytics_routes.py  # Analytics endpoints
│   │   ├── auth_routes.py       # /api/v1/auth (MSAL, sessions)
│   │   ├── health_routes.py     # /api/v1/health
│   │   ├── onboarding_guide_routes.py # Onboarding endpoints
│   │   ├── ppt_addin_routes.py  # PPT add-in endpoints
│   │   ├── project_routes.py    # Project CRUD/listing
│   │   └── user_routes.py       # User profile endpoints
│   ├── database/
│   │   ├── database_initialize.py # Legacy/init helpers
│   │   ├── database_manager.py  # DB ops & alembic wrappers
│   │   └── database_migration.py# Migration helpers/rollback
│   ├── middleware/
│   │   ├── analytics_middleware.py # Request/session analytics
│   │   └── auth_session_middleware.py # Client/session extraction
│   ├── models/
│   │   ├── database_models.py   # ORM models
│   │   └── document.py          # Document helpers
│   ├── preprocessing/
│   │   ├── csv_processor.py     # CSV/Excel preprocessing
│   │   ├── document_processor.py# Orchestrates preprocessing
│   │   ├── docx_processor.py    # Word processing
│   │   ├── image_processor.py   # OCR for images
│   │   ├── pdf_processor.py     # PDF processing
│   │   ├── pptx_processor.py    # PPTX processing
│   │   └── chunking/
│   │       ├── __init__.py      # Package marker
│   │       ├── models.py        # Chunk models
│   │       ├── nlp_processor.py # NLP utils
│   │       ├── strategies.py    # Chunking strategies
│   │       └── token_counter.py # Token counting
│   ├── prompts/                 # Prompt templates (mirrors functions)
│   ├── services/
│   │   ├── analytics_service.py # Aggregates analytics
│   │   ├── auth_service.py      # Tokens/sessions lifecycle
│   │   ├── blob_storage_service.py # Azure Blob client
│   │   ├── classification.py    # Classification logic
│   │   ├── document_upload_service.py # Upload handling
│   │   ├── local_storage_service.py   # Local storage backend
│   │   ├── metadata_manager.py  # Metadata extraction/management
│   │   ├── onboarding_guide_service.py # Onboarding generation
│   │   ├── ppt_improve_selected_text_service.py # Improve selected text
│   │   ├── ppt_parallelize_content_service.py   # Parallelize content
│   │   ├── ppt_slide_structure.py # Slide structure ops
│   │   ├── ppt_title_refine_service.py # Title refinement
│   │   ├── ppt_title_service.py  # Title generation
│   │   ├── project_service.py    # Project operations
│   │   ├── rag/
│   │   │   ├── citation_formatter.py # Citation formatting (API)
│   │   │   ├── csv_index_builder.py  # CSV indexing (API)
│   │   │   ├── embed_chunks.py       # Chunk embedding (API)
│   │   │   ├── index_builder.py      # Vector index build (API)
│   │   │   ├── node_converter.py     # Doc→node conversion (API)
│   │   │   ├── query_engine.py       # Query engine (API)
│   │   │   ├── query_executor.py     # Retrieval + synthesis (API)
│   │   │   └── retriever_service.py  # Retriever setup/search (API)
│   │   ├── service_bus_sender.py # Azure Service Bus sender
│   │   ├── slide_review_service.py # Slide review
│   │   ├── storage_factory.py   # Chooses storage backend
│   │   ├── storage_service_base.py # Storage interface
│   │   ├── summarization.py     # Summarization logic
│   │   └── summarychunking.py   # Summary chunking for long texts
│   ├── ui/
│   │   ├── file_upload_app.py   # Minimal upload UI
│   │   └── summarization_app.py # Minimal summarization UI
│   └── utils/
│       ├── api_tracker.py       # API usage tracking
│       ├── auth_utils.py        # Hashing/JWT/cookie helpers
│       ├── classification_utils.py # Classification utilities
│       ├── config.py            # App config & env (requires GEMINI_API_KEY)
│       ├── constants.py         # Constants
│       ├── database.py          # DB session utilities
│       ├── database_utils.py    # DB helpers
│       ├── exceptions.py        # Exception classes
│       ├── gemini_client.py     # Gemini API client
│       ├── prompt_generators.py # Programmatic prompts
│       ├── prompt_loader.py     # Loads prompt templates
│       └── response_utils.py    # Standard API responses
├── README.md                    # This documentation
├── MIGRATION.md                 # Migration guidelines/notes
├── test_database.py             # DB tests
└── temp_uploads/, data™, tmp/, venv/, venv_test/ # Local dirs/envs
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

```bash
python run.py
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

- Create a feature branch
- Add tests and docs
- Ensure formatting/linting passes
- Open a PR

## 📄 File Reference (Brief Descriptions)

Top-level
- README.md: This documentation
- API_ROUTES_ORGANIZATION.md: High-level map of API endpoints and groupings
- alembic.ini: Alembic configuration for migrations
- base.Dockerfile: Base image for multi-stage Docker builds
- Dockerfile: Application Docker build recipe
- entrypoint.sh: Container startup script
- main.py: Flask app factory, CORS, middleware, and blueprint registration
- manage.py: CLI wrapping Alembic operations and DB tasks
- MIGRATION.md: Notes and guidance on database migrations
- requirements.txt: Core Python dependencies
- requirements-azure.txt: Azure deployment dependencies
- requirements-2.txt: Auxiliary/legacy requirements (if used)
- run.py: Development server launcher at port 8000
- test_database.py: Database test harness
- wsgi.py: Production WSGI entrypoint
- sshd_config: SSH daemon configuration (if used in containers)
- data/: Project data directory (runtime artifacts)
- temp_uploads/: Temporary uploads during processing
- tmp/: Temporary working directory
- venv/, venv_test/: Local virtual environments (ignored in production)

migrations/
- __init__.py: Package marker
- env.py: Alembic environment config (DB connection and setup)
- script.py.mako: Template for autogenerated migration scripts
- versions/__init__.py: Package marker
- versions/2025_07_28_1748-fd1c410f9841_initial_database_schema.py: Initial DB schema
- versions/2025_08_04_0828-d02dda149530_add_source_column_to_documentsummary_.py: Adds source column

azure_functions/
- Dockerfile: Azure Functions container build
- host.json: Azure Functions host configuration
- local.settings.example.json: Local dev settings example

azure_functions/DocumentProcessor/
- __init__.py: Entry for the document processing function
- function.json: Trigger/binding configuration

azure_functions/OnboardingProcessor/
- __init__.py: Entry for the onboarding processor function
- function.json: Trigger/binding configuration

azure_functions/database/
- database_manager.py: DB helper utilities for functions runtime

azure_functions/models/
- database_models.py: SQLAlchemy ORM models shared in functions
- document.py: Document model helpers for functions

azure_functions/preprocessing/
- csv_processor.py: CSV/Excel preprocessing pipeline for functions
- document_processor.py: Orchestrates preprocessing and metadata extraction
- docx_processor.py: Microsoft Word preprocessing
- image_processor.py: OCR pipeline for image files
- pdf_processor.py: PDF text and layout extraction
- pptx_processor.py: PowerPoint preprocessing

azure_functions/preprocessing/chunking/
- __init__.py: Package marker
- chunking_config.py: Chunking configuration and defaults
- models.py: Data structures for chunks and metadata
- nlp_processor.py: NLP utilities used during chunking
- strategies.py: Chunking strategies implementations
- token_counter.py: Tokenization and token counting helpers
- validators.py: Validation helpers for chunking outputs

azure_functions/prompts/
- *.txt: Prompt templates used in function workflows
- ppt_addin_prompts/*.txt: Add-in specific prompts for PPT operations

azure_functions/services/
- blob_storage_service.py: Azure Blob Storage client abstraction
- classification.py: AI document classification service
- document_upload_service.py: Handles intake and routing of uploads
- metadata_manager.py: Metadata extraction and management
- onboarding_guide_service.py: Creates onboarding guides from sources
- service_bus_sender.py: Azure Service Bus producer utilities
- storage_service_base.py: Storage service interface for pluggability
- summarization.py: Summarization service helpers

azure_functions/services/rag/
- answer_verifier.py: Post-answer verification (consistency/grounding)
- citation_formatter.py: Formats citations for answers
- config_loader.py: Loads RAG configuration
- csv_index_builder.py: Builds indices from CSVs
- embed_chunk.py: Embeds chunks for vector stores
- fusion.py: Fusion search utilities
- index_builder.py: RAG index construction pipeline
- intent_router.py: Intent detection and routing
- llm_service.py: LLM wrapper for RAG steps
- node_converter.py: Converts docs to RAG nodes
- planner.py: Query planning for multi-step answers
- post_retrieval.py: Post-retrieval augmentation steps
- query_engine.py: Query engine configuration for functions
- query_executor.py: Executes the RAG pipeline
- query_orchestrator.py: High-level orchestrator for query flows
- reranker.py: Re-ranking of retrieved results
- retrieval_service.py: Retriever setup and search
- test.py: Local test harness for RAG components

azure_functions/utils/
- api_tracker.py: API usage and quota tracking for functions
- auth_utils.py: Auth helpers (tokens/cookies) for functions
- classification.py: Shared classification helpers
- classification_utils.py: Utilities for classification pipelines
- config.py: Settings loader for functions
- constants.py: Constants used in functions code
- database.py: Database connection utilities for functions
- exceptions.py: Custom exceptions for functions
- gemini_client.py: Gemini API client wrapper for functions
- logging.py: Logging configuration for functions
- prompt_generators.py: Helpers to generate prompts dynamically
- prompt_loader.py: Loads prompt templates
- summarization.py: Summarization helpers for functions


giani_pkb/
- __init__.py: Package marker

giani_pkb/api/
- __init__.py: Blueprint factory exports
- analytics_routes.py: Analytics endpoints (user/system metrics)
- auth_routes.py: Auth endpoints (/api/v1/auth/*, MSAL, sessions)
- health_routes.py: System and DB health endpoints
- onboarding_guide_routes.py: Onboarding guide API endpoints
- ppt_addin_routes.py: PowerPoint add-in endpoints
- project_routes.py: Project-level CRUD and listing
- user_routes.py: User profile and management endpoints

giani_pkb/database/
- __init__.py: Package marker
- database_initialize.py: Legacy/utility DB initialization
- database_manager.py: Unified DB operations and Alembic wrappers
- database_migration.py: Helpers for migration management/rollback

giani_pkb/middleware/
- __init__.py: Package marker
- analytics_middleware.py: Request/session analytics tracking
- auth_session_middleware.py: Client/session extraction and auth helpers

giani_pkb/models/
- __init__.py: Package marker
- database_models.py: SQLAlchemy ORM models (users, projects, docs, etc.)
- document.py: Document model helper functions

giani_pkb/preprocessing/
- __init__.py: Package marker
- csv_processor.py: CSV/Excel preprocessing for API side
- document_processor.py: Orchestrates API-side preprocessing
- docx_processor.py: Word document processing
- image_processor.py: OCR for images
- pdf_processor.py: PDF processing
- pptx_processor.py: PowerPoint processing
- test_chunking_strategies.py: Tests for chunking strategies
- test_processing.py: Tests for processing pipelines

giani_pkb/preprocessing/chunking/
- __init__.py: Package marker
- models.py: Chunk/segment data structures
- nlp_processor.py: NLP utilities for chunking
- strategies.py: Chunking strategies
- token_counter.py: Token counting utilities

giani_pkb/prompts/
- __init__.py: Package marker
- *.txt: Prompt templates (mirrors functions prompts)
- ppt_addin_prompts/*.txt: PPT add-in prompt templates

giani_pkb/services/
- __init__.py: Package marker
- analytics_service.py: Aggregates analytics data
- auth_service.py: Token/session lifecycle and validation
- blob_storage_service.py: Azure Blob client for API service
- classification.py: Classification business logic
- document_upload_service.py: API upload handling and dispatch
- local_storage_service.py: Local filesystem storage implementation
- metadata_manager.py: Document metadata extraction/management
- onboarding_guide_service.py: Onboarding guide generation logic
- ppt_improve_selected_text_service.py: Improves selected PPT text
- ppt_parallelize_content_service.py: Parallelizes PPT content
- ppt_slide_structure.py: Slide structure generation/refinement
- ppt_title_refine_service.py: Refines PPT slide titles
- ppt_title_service.py: Generates PPT slide titles
- project_service.py: Project operations
- service_bus_sender.py: Azure Service Bus sender for API
- slide_review_service.py: Reviews slide content for quality
- storage_factory.py: Chooses storage backend (local/blob)
- storage_service_base.py: Storage interface base class
- summarization.py: Summarization business logic
- summarychunking.py: Summary chunking logic for long texts

giani_pkb/services/rag/
- citation_formatter.py: Formats citations for answers (API side)
- csv_index_builder.py: Builds CSV indices (API side)
- embed_chunks.py: Embeds chunks (API side)
- index_builder.py: Builds vector indices (API side)
- node_converter.py: Converts docs to RAG nodes (API side)
- query_engine.py: Query engine configuration (API side)
- query_executor.py: Executes retrieval and synthesis (API side)
- retriever_service.py: Retriever setup and search (API side)

giani_pkb/ui/
- __init__.py: Package marker
- file_upload_app.py: Minimal UI for uploading files
- summarization_app.py: Minimal UI for text/document summarization

giani_pkb/utils/
- __init__.py: Package marker
- api_tracker.py: API usage tracking utilities
- auth_utils.py: Password hashing, JWT helper, cookie/token extraction
- classification_utils.py: Classification utility functions
- config.py: Application configuration and env loader (requires GEMINI_API_KEY)
- constants.py: Project-wide constants
- database.py: DB connection/session utilities
- database_utils.py: DB utility helpers
- exceptions.py: Common exception classes
- gemini_client.py: Gemini API client wrapper
- prompt_generators.py: Generates prompts programmatically
- prompt_loader.py: Loads file-based prompt templates
- response_utils.py: Standardized API response helpers