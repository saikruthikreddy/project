import logging
import sys
import json
import azure.functions as func
import os
from datetime import datetime

from utils.logging import setup_logging


# This allows the function to import from the shared_code directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from services.service_bus_sender import onboarding_service_bus
from services.document_upload_service import DocumentUploadService
from database.database_manager import DatabaseManager

# Set up logging
logger = setup_logging()

def main(msg: func.ServiceBusMessage):
    logger.info("✅ Function triggered")

    try:
        message_body = msg.get_body().decode("utf-8")
        task_data = json.loads(message_body)
        logger.info(f"Processing task: {task_data}")

        batch_id = task_data.get("batch_id")
        project_id = task_data.get("project_id")

        upload_service = DocumentUploadService()
        db_manager = DatabaseManager()

        batch = db_manager.get_processing_batch(batch_id)
        if not batch:
            raise ValueError("No batch found with the given batch_id")

        if batch["status"] == "QUEUED":
            db_manager.update_batch_status(batch_id, "PROCESSING")

        # Process the document
        result = upload_service.process_single_document(task_data)
        logger.info(f"Document processing completed: {result}")
        db_manager.increment_batch_progress(batch_id, True)

        # Check if batch is complete and send onboarding message
        batch_id = task_data.get("batch_id")
        project_id = task_data.get("project_id")

        if batch_id and project_id:
            batch_status = db_manager.get_batch_status(batch_id)
            logger.info(f"✅ Document processed, batch_status = {batch_status["status"]}")

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
        # db_manager.increment_batch_progress(batch_id, False) # TODO: Cannot do this here as this gets run on retries as well, should probably be done when the message is sent to dead-letter queue
        logger.error(f"Error processing document: {e}", exc_info=True)
        # The message will be automatically dead-lettered by Azure Functions on failure
        raise
