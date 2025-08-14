import logging
import json
import azure.functions as func
import os

# This allows the function to import from the shared_code directory
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from services.document_upload_service import DocumentUploadService
from database.database_manager import DatabaseManager
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from utils.config import config

def main(msg: func.ServiceBusMessage):
    logging.info("Python ServiceBus queue trigger function processed a message.")

    try:
        message_body = msg.get_body().decode("utf-8")
        task_data = json.loads(message_body)
        logging.info(f"Processing task: {task_data}")

        batch_id = task_data.get("batch_id")
        project_id = task_data.get("project_id")

        upload_service = DocumentUploadService()
        db_manager = DatabaseManager()

        # Process the document
        result = upload_service._process_single_document(task_data)
        logging.info(f"Document processing completed: {result}")

        # Check if batch is complete and send onboarding message
        batch_id = task_data.get("batch_id")
        project_id = task_data.get("project_id")

        if batch_id and project_id:
            batch_status = db_manager.get_batch_status(batch_id)

            if batch_status and batch_status.get("is_complete"):
                logging.info(
                    f"Batch {batch_id} is complete. Queuing project {project_id} for onboarding guide generation."
                )

                conn_str = config.SERVICE_BUS_CONNECTION_STRING
                onboarding_queue_name = "project-onboarding-queue"

                with ServiceBusClient.from_connection_string(conn_str) as client:
                    sender = client.get_queue_sender(onboarding_queue_name)
                    with sender:
                        onboarding_message_payload = {
                            "project_id": project_id,
                            "triggered_by_batch_id": batch_id,
                        }
                        message = ServiceBusMessage(
                            json.dumps(onboarding_message_payload)
                        )
                        sender.send_messages(message)
                logging.info(
                    f"Successfully queued project {project_id} for onboarding guide generation."
                )

    except Exception as e:
        logging.error(f"Error processing document: {e}", exc_info=True)
        # The message will be automatically dead-lettered by Azure Functions on failure
        raise
