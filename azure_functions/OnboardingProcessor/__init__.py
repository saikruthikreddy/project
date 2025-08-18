import logging
import json
import azure.functions as func
import os

import sys

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from services.onboarding_guide_service import OnboardingGuideGenerator
from database.database_manager import DatabaseManager

def main(msg: func.ServiceBusMessage):
    logging.info("Onboarding guide generation trigger processed a message.")

    try:
        message_body = msg.get_body().decode("utf-8")
        task_data = json.loads(message_body)
        project_id = task_data.get("project_id")

        if not project_id:
            logging.error("Message is missing 'project_id'.")
            return

        logging.info(f"Generating onboarding guide for project {project_id}.")

        # Instantiate services
        db_manager = DatabaseManager()
        guide_generator = OnboardingGuideGenerator(db_manager)

        # Generate the guide
        onboarding_guide = guide_generator.generate_onboarding_guide(project_id)

        # TODO: Save the guide and update database
        if "error" in onboarding_guide:
            logging.error(
                f"Failed to generate guide for project {project_id}: {onboarding_guide['details']}"
            )
        else:
            logging.info(
                f"Successfully generated onboarding guide for project {project_id}."
            )
            # Example: Save to a 'guides' container in blob storage
            # storage_service.upload_file('guides', f'{project_id}-onboarding-guide.json', json.dumps(onboarding_guide).encode('utf-8'))

    except Exception as e:
        logging.error(f"Error generating onboarding guide: {e}", exc_info=True)
        raise
