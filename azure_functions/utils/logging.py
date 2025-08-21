import logging
import sys

# Force console logging for local development
def setup_logging():
    """Setup logging to ensure it works in Azure Functions local environment"""
    logger = logging.getLogger()

    # Remove existing handlers to avoid conflicts
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)

    return logger