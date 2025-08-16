from azure.servicebus import ServiceBusClient, ServiceBusMessage
import os
import json
import uuid
import logging
from datetime import datetime

from utils.config import config


logger = logging.getLogger(__name__)
SERVICE_BUS_CONNECTION_STRING = getattr(config, "SERVICE_BUS_CONNECTION_STRING", "")

class ServiceBusSender:
    def __init__(self, queue_name: str):
        if not SERVICE_BUS_CONNECTION_STRING:
            raise ValueError(
                "SERVICE_BUS_CONNECTION_STRING is not set in env variables."
            )

        if not queue_name:
            raise ValueError("Queue name is required.")

        self.client = ServiceBusClient.from_connection_string(
            SERVICE_BUS_CONNECTION_STRING
        )
        self.queue_name = queue_name

    def _serialize_datetime(self, obj):
        """Custom JSON serializer for datetime objects"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def _prepare_payload(self, payload):
        """Prepare payload for JSON serialization by converting datetime objects"""
        return json.loads(json.dumps(payload, default=self._serialize_datetime))

    def send_document_task(self, task_data: dict):
        try:
            with self.client:
                sender = self.client.get_queue_sender(queue_name=self.queue_name)
                with sender:
                    prepared_data = self._prepare_payload(task_data)
                    message_id = str(task_data.get("temp_document_id") or uuid.uuid4())

                    msg = ServiceBusMessage(
                        body=json.dumps(prepared_data),
                        content_type="application/json",
                        message_id=message_id,
                    )
                    sender.send_messages(msg)
                    logger.info(
                        f"[ServiceBus] Sent message to '{self.queue_name}' with message_id={message_id}"
                    )
        except Exception as e:
            logger.error(
                f"[ServiceBus] Failed to send single message to '{self.queue_name}': {e}",
                exc_info=True,
            )
            raise

    def send_batch(self, payloads: list):
        """Send a batch of messages."""
        try:
            with self.client:
                sender = self.client.get_queue_sender(queue_name=self.queue_name)
                with sender:
                    batch = sender.create_message_batch()

                    for payload in payloads:
                        try:
                            prepared_payload = self._prepare_payload(payload)
                            message_id = str(
                                payload.get("temp_document_id") or uuid.uuid4()
                            )
                            msg = ServiceBusMessage(
                                body=json.dumps(prepared_payload),
                                content_type="application/json",
                                message_id=message_id,
                            )

                            batch.add_message(msg)
                        except ValueError:
                            # Batch is full, send and create new batch
                            sender.send_messages(batch)
                            batch = sender.create_message_batch()
                            batch.add_message(msg)
                            logger.debug(
                                "[ServiceBus] New batch started after sending full batch."
                            )

                    # Send any remaining messages
                    if len(batch) > 0:
                        sender.send_messages(batch)

            logger.info(
                f"[ServiceBus] Sent batch of {len(payloads)} messages to '{self.queue_name}'."
            )

        except Exception as e:
            logger.error(
                f"[ServiceBus] Failed to send batch to '{self.queue_name}': {e}",
                exc_info=True,
            )
            raise


DOCUMENT_PROCESSING_QUEUE = getattr(config, "DOCUMENT_PROCESSING_QUEUE", "")
ONBOARDING_PROCESSING_QUEUE = getattr(config, "ONBOARDING_PROCESSING_QUEUE", "")

if not DOCUMENT_PROCESSING_QUEUE:
    logger.info(
        f"Missing document processing queue. DOCUMENT_PROCESSING_QUEUE not set in env"
    )
if not ONBOARDING_PROCESSING_QUEUE:
    logger.info(
        f"Missing document processing queue. ONBOARDING_PROCESSING_QUEUE not set in env"
    )

document_service_bus = ServiceBusSender(queue_name=DOCUMENT_PROCESSING_QUEUE)
onboarding_service_bus = ServiceBusSender(queue_name=ONBOARDING_PROCESSING_QUEUE)
