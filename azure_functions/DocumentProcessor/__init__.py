import logging
from logging.handlers import RotatingFileHandler  # Added missing import
import sys
import json
import azure.functions as func
import os
from datetime import datetime


# This allows the function to import from the shared_code directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from azure_functions.services.service_bus_sender import onboarding_service_bus
from services.document_upload_service import DocumentUploadService
from database.database_manager import DatabaseManager
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from utils.config import config

def setup_comprehensive_logging():
    """Setup logging to capture ALL application logs to both console and file"""

    # Create a custom filter to exclude Azure Functions noise but keep our app logs
    class AppLogFilter(logging.Filter):
        def filter(self, record):
            # Exclude these specific Azure/system loggers from console
            excluded_from_console = [
                'azure.functions.meta',
                'azure.functions._thirdparty',
                'azure.core.pipeline',
                'WorkerProcess',
                'grpc._channel',
                'urllib3.connectionpool'
            ]

            # But allow everything in the file
            if hasattr(self, 'for_file') and self.for_file:
                return True

            # For console, filter out the noise
            for excluded in excluded_from_console:
                if record.name.startswith(excluded):
                    return False
            return True

    # Get the root logger to capture everything
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Setup file logging directory
    try:
        log_dir = os.path.abspath("logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, "comprehensive_app.log")

        # File handler - captures EVERYTHING (no filter)
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=20*1024*1024,  # 20MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)

        # Create a special filter for file that allows everything
        file_filter = AppLogFilter()
        file_filter.for_file = True
        file_handler.addFilter(file_filter)

        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

        # Test file logging immediately
        with open(log_file_path, "a") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"NEW FUNCTION SESSION STARTED: {datetime.now()}\n")
            f.write(f"{'='*80}\n")

        print(f"📝 Comprehensive logging to: {log_file_path}")

    except Exception as e:
        print(f"⚠️  File logging setup failed: {e}")
        import traceback
        print(traceback.format_exc())

    # Console handler - filtered for clean output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.addFilter(AppLogFilter())
    console_formatter = logging.Formatter('🔥 %(levelname)s - %(name)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    return root_logger

# Setup comprehensive logging
logger = setup_comprehensive_logging()

def main(msg: func.ServiceBusMessage, context: func.Context):
    logger.info("✅ Function triggered")
    batch_id = None
    db_manager = None  # Initialize to None at the start
    
    try:
        message_body = msg.get_body().decode("utf-8")
        task_data = json.loads(message_body)
        logger.info(f"Processing task: {task_data}")

        batch_id = task_data.get("batch_id")
        project_id = task_data.get("project_id")

        upload_service = DocumentUploadService()
        db_manager = DatabaseManager()  # Initialize db_manager here

        batch = db_manager.get_processing_batch(batch_id)
        if not batch:
            raise ValueError("No batch found with the given batch_id")

        if batch["status"] == "QUEUED":
            db_manager.update_batch_status(batch_id, "PROCESSING")

        # Process the document
        result = upload_service._process_single_document(task_data)
        logger.info(f"Document processing completed: {result}")
        db_manager.increment_batch_progress(batch_id, True)

        # Check if batch is complete and send onboarding message
        batch_id = task_data.get("batch_id")
        project_id = task_data.get("project_id")

        if batch_id and project_id:
            batch_status = db_manager.get_batch_status(batch_id)
            logger.info(f"✅ Document processed, batch_status = {batch_status['status']}")

            if batch_status and batch_status["status"] == 'COMPLETED':
                logger.info(
                    f"Batch {batch_id} is complete. Queuing project {project_id} for onboarding guide generation."
                )
                onboarding_message_payload = {
                    "project_id": project_id,
                    "triggered_by_batch_id": batch_id,
                }
                onboarding_service_bus.send_document_task(onboarding_message_payload)
                logger.info(
                    f"Successfully queued project {project_id} for onboarding guide generation."
                )

    except Exception as e:
        logger.error(f"Error processing document: {e}", exc_info=True)
        if batch_id and context.retry_context and (context.retry_context.retry_count == context.retry_context.max_retry_count):
            logger.error(f"Message for batch {batch_id} has reached max retries. Marking as failed.")
            # Only call db_manager if it was successfully initialized
            if db_manager is not None:
                try:
                    db_manager.increment_batch_progress(batch_id, False)
                except Exception as db_error:
                    logger.error(f"Failed to update batch progress in exception handler: {db_error}", exc_info=True)
            else:
                logger.error(f"Cannot update batch progress - db_manager was not initialized")
        
        # The message will be automatically dead-lettered by Azure Functions on failure
        raise