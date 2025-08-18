# API Routes Organization

## Overview

All API routes have been consolidated into the `giani_pkb/api/` folder for better organization and maintainability. The routes are now properly separated by domain and follow consistent patterns.

## Route Structure

```
giani_pkb/api/
├── __init__.py              # Package initialization and exports
├── auth_routes.py           # Authentication routes (/auth/*)
├── project_routes.py        # Project management routes (/api/v1/projects/*)
├── user_routes.py          # User management routes (/api/v1/users/*)
└── health_routes.py        # Health check routes (/api/v1/health/*)
```

## Route Categories

### 1. Authentication Routes (`auth_routes.py`)
**Base URL**: `/auth`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/test` | GET, POST, OPTIONS | CORS test endpoint |
| `/login` | POST | Username/password login |
| `/login/microsoft` | POST | Microsoft OAuth login |
| `/refresh` | POST | Refresh access token |
| `/logout` | POST | Logout user |
| `/me` | GET | Get current user info |
| `/register` | POST | Register new user |
| `/health` | GET | Auth service health |

### 2. Project Routes (`project_routes.py`)
**Base URL**: `/api/v1/projects`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/test` | GET, POST, OPTIONS | CORS test endpoint |
| `/projects` | POST | Create new project |
| `/projects/` | GET | List all projects |
| `/projects/<project_id>` | GET | Get project details |
| `/projects/<project_id>` | PUT | Update project |
| `/projects/<project_id>` | DELETE | Delete project |
| `/projects/<project_id>/documents/upload` | POST | Upload document to project |
| `/projects/<project_id>/documents/ai-suggestions` | POST | Get AI suggestions |
| `/projects/<project_id>/documents/process-batch` | POST | Process batch of documents |
| `/projects/<project_id>/documents` | GET | List project documents |
| `/batches/<batch_id>/status` | GET | Get batch processing status |
| `/role-purpose-categories` | GET | Get classification categories |
| `/project_id/<document_id>` | GET | Get document details |
| `/project_id/<document_id>` | PUT | Update document metadata |
| `/project_id/<document_id>` | DELETE | Delete document |
| `/project_id/<document_id>/chunks` | GET | Get document chunks |
| `/project_id/<document_id>/summaries` | GET | Get document summaries |
| `/project_id/<document_id>/classify` | POST | Reclassify document with AI |

### 4. User Routes (`user_routes.py`)
**Base URL**: `/api/v1/users`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/profile` | GET | Get user profile |
| `/profile` | PUT | Update user profile |
| `/change-password` | POST | Change user password |
| `/documents` | GET | Get all user documents |
| `/statistics` | GET | Get user statistics |
| `/register` | POST | Register new user |

### 5. Health Routes (`health_routes.py`)
**Base URL**: `/api/v1/health`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Basic health check |
| `/detailed` | GET | Detailed health with system info |
| `/database` | GET | Database-specific health check |
| `/system` | GET | System resources health check |
| `/services` | GET | External services health check |
| `/ready` | GET | Readiness check for containers |

## Response Format

All routes use the standardized API response format:

### Success Response
```json
{
  "success": true,
  "data": {
    // Response data
  },
  "message": "Operation completed successfully",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### Error Response
```json
{
  "success": false,
  "error": {
    "message": "Error description",
    "code": "ERROR_CODE",
    "details": {}
  },
  "timestamp": "2024-01-01T00:00:00Z"
}
```

## Blueprint Registration

All routes are registered in `main.py` using Flask blueprints:

```python
# Register all route blueprints
app.register_blueprint(create_auth_routes())
app.register_blueprint(create_project_routes())
app.register_blueprint(create_user_routes())
app.register_blueprint(create_health_routes())
```

## Usage Examples

### Creating a New Route Category

1. Create a new file in `giani_pkb/api/` (e.g., `analytics_routes.py`)
2. Define the blueprint with proper URL prefix
3. Add routes with consistent error handling
4. Export the create function in `__init__.py`
5. Register the blueprint in `main.py`

### Adding Routes to Existing Categories

1. Open the appropriate route file
2. Add new route functions following the existing pattern
3. Use the standardized response utilities
4. Add proper error handling and logging

## Error Handling

All routes use the centralized error handling system:

```python
from giani_pkb.utils.exceptions import ValidationError, NotFoundError
from giani_pkb.utils.response_utils import api_success, api_error

try:
    # Route logic
    return api_success(data, "Success message")
except ValidationError as e:
    return api_error(str(e), 400)
except NotFoundError as e:
    return api_error(str(e), 404)
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    return api_error("Internal server error", 500)
```

## Testing

Each route category can be tested independently:

```bash
# Test auth routes
curl -X POST http://localhost:5000/auth/test

# Test project routes
curl -X GET http://localhost:5000/api/v1/projects/

# Test health routes
curl -X GET http://localhost:5000/api/v1/health/status
```

## Future Enhancements

1. **API Versioning**: Easy to add versioned routes (e.g., `/api/v2/`)
2. **Rate Limiting**: Can be added per route category
3. **Caching**: Route-specific caching strategies
4. **Monitoring**: Per-category metrics and monitoring
5. **Documentation**: Auto-generated API documentation from route definitions