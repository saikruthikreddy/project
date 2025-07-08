#!/bin/bash

# Azure Deployment Script for Giani AI Project Knowledge Base
# Make sure you're logged in to Azure CLI before running this script

# Configuration variables
RESOURCE_GROUP_NAME="giani-ai-rg"
LOCATION="centralindia"
APP_SERVICE_PLAN_NAME="giani-ai-plan"
APP_SERVICE_NAME="giani-ai-app-deployment-2"  # This needs to be globally unique
POSTGRES_SERVER_NAME="giani-ai-db-server-deployment-3"  # This needs to be globally unique
POSTGRES_DB_NAME="giani_ai_db"
POSTGRES_ADMIN_USER="gianiadmin"

read -s -p "Enter PostgreSQL Admin Password: " POSTGRES_ADMIN_PASSWORD
echo
read -s -p "Enter Azure Deployment User Password: " DEPLOY_PASSWORD
echo
# ... use $POSTGRES_ADMIN_PASSWORD and $DEPLOY_PASSWORD later

echo "🚀 Starting Azure deployment for Giani AI Project Knowledge Base..."

set -e # Exit immediately if any command fails, preventing partial deployments.

# Step 1: Create Resource Group
echo "📦 Creating Resource Group..."
az group create \
  --name $RESOURCE_GROUP_NAME \
  --location "$LOCATION"

# Step 2: Create PostgreSQL Server
# echo "🐘 Creating PostgreSQL Server..."
# az postgres flexible-server create \
#   --resource-group $RESOURCE_GROUP_NAME \
#   --name $POSTGRES_SERVER_NAME \
#   --location "$LOCATION" \
#   --admin-user $POSTGRES_ADMIN_USER \
#   --admin-password $POSTGRES_ADMIN_PASSWORD \
#   --tier Burstable \
#   --sku-name Standard_B1ms \
#   --storage-size 32 \
#   --version 16 \
#   --public-access 0.0.0.0

# Step 3: Create database
echo "🗄️ Creating Database..."
az postgres flexible-server db create \
  --resource-group $RESOURCE_GROUP_NAME \
  --server-name $POSTGRES_SERVER_NAME \
  --database-name $POSTGRES_DB_NAME

# Step 4: Create App Service Plan
echo "📋 Creating App Service Plan..."
az appservice plan create \
  --resource-group $RESOURCE_GROUP_NAME \
  --name $APP_SERVICE_PLAN_NAME \
  --location "$LOCATION" \
  --sku B1 \
  --is-linux

# Step 5: Create Web App
echo "🌐 Creating Web App..."
az webapp create \
  --resource-group $RESOURCE_GROUP_NAME \
  --plan $APP_SERVICE_PLAN_NAME \
  --name $APP_SERVICE_NAME \
  --runtime "PYTHON:3.11" \
  --deployment-local-git

# Step 6: Configure App Settings
echo "⚙️ Configuring App Settings..."

# Get PostgreSQL connection string
POSTGRES_CONNECTION_STRING="postgresql://$POSTGRES_ADMIN_USER:$POSTGRES_ADMIN_PASSWORD@$POSTGRES_SERVER_NAME.postgres.database.azure.com:5432/$POSTGRES_DB_NAME"

# Set application settings
az webapp config appsettings set \
  --resource-group $RESOURCE_GROUP_NAME \
  --name $APP_SERVICE_NAME \
  --settings \
    FLASK_ENV=production \
    DATABASE_URL="$POSTGRES_CONNECTION_STRING" \
    JWT_SECRET="your-secure-jwt-secret-here" \
    GEMINI_API_KEY="your-gemini-api-key-here" \
    CORS_ORIGINS="http://localhost:3000,https://$APP_SERVICE_NAME.azurewebsites.net" \
    LOG_LEVEL=INFO \
    SCM_DO_BUILD_DURING_DEPLOYMENT=1 \
    POST_BUILD_COMMAND="python -c \"from giani_pkb.database.database_initialize import DatabaseInitializer; DatabaseInitializer().initialize_database()\""

# Step 7: Configure startup command
echo "🚀 Configuring startup command..."
az webapp config set \
  --resource-group $RESOURCE_GROUP_NAME \
  --name $APP_SERVICE_NAME \
  --startup-file "gunicorn --bind 0.0.0.0:8000 --timeout 600 --workers 4 startup:app"

# Step 8: Get deployment credentials
echo "🔑 Getting deployment credentials..."
az webapp deployment user set \
  --user-name "gianiai-deploy-2025" \
  --password $DEPLOY_PASSWORD

# Get the Git URL for deployment
GIT_URL=$(az webapp deployment source config-local-git \
  --resource-group $RESOURCE_GROUP_NAME \
  --name $APP_SERVICE_NAME \
  --query url \
  --output tsv)

echo "✅ Azure resources created successfully!"
echo ""
echo "📝 Deployment Information:"
echo "Resource Group: $RESOURCE_GROUP_NAME"
echo "App Service: $APP_SERVICE_NAME"
echo "PostgreSQL Server: $POSTGRES_SERVER_NAME"
echo "Web App URL: https://$APP_SERVICE_NAME.azurewebsites.net"
echo "Git Deployment URL: $GIT_URL"
echo ""
echo "🔧 Next Steps:"
echo "1. Update your environment variables in the Azure portal"
echo "2. Deploy your code using Git"
echo "3. Test your application"
echo ""
echo "📋 To deploy your code, run:"
echo "git remote add azure $GIT_URL"
echo "git push azure main"