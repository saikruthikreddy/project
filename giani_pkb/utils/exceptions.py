# Defines custom exceptions for the Giani PKB application.

class GianiBaseError(Exception):
    """Base class for custom exceptions in the Giani PKB application."""
    pass

class ConfigurationError(GianiBaseError):
    """Exception raised for errors in the application configuration.

    Attributes:
        message -- explanation of the error
    """
    def __init__(self, message="A configuration error occurred."):
        self.message = message
        super().__init__(self.message)

class APIError(GianiBaseError):
    """Exception raised for errors occurring during API calls.

    Attributes:
        message -- explanation of the error
        status_code -- optional HTTP status code from the API response
    """
    def __init__(self, message="An error occurred while communicating with an external API.", status_code=None):
        self.message = message
        self.status_code = status_code
        details = f"{message}"
        if status_code:
            details += f" (Status Code: {status_code})"
        super().__init__(details)

class ParsingError(GianiBaseError):
    """Exception raised for errors during parsing of files or data.

    Attributes:
        message -- explanation of the error
        filename -- optional name of the file that caused the parsing error
    """
    def __init__(self, message="An error occurred while parsing data or a file.", filename=None):
        self.message = message
        self.filename = filename
        details = f"{message}"
        if filename:
            details += f" (File: {filename})"
        super().__init__(details)

class FileProcessingError(GianiBaseError):
    """Exception raised for general errors during file processing not covered by ParsingError."""
    def __init__(self, message="An error occurred during file processing.", filepath=None):
        self.message = message
        self.filepath = filepath
        details = f"{message}"
        if filepath:
            details += f" (File: {filepath})"
        super().__init__(details)

# Example of how these might be used:
#
# from .exceptions import APIError, ParsingError, ConfigurationError
#
# def load_config():
#     api_key = os.getenv("API_KEY")
#     if not api_key:
#         raise ConfigurationError("API_KEY is not set in the environment.")
#
# def fetch_data_from_api(request):
#     response = make_api_call(request)
#     if response.status_code != 200:
#         raise APIError(f"API request failed with status {response.status_code}", status_code=response.status_code)
#     try:
#         data = json.loads(response.text)
#         return data
#     except json.JSONDecodeError as e:
#         raise ParsingError(f"Failed to parse JSON response from API: {e}")
#
# def process_document(filepath):
#     try:
#         with open(filepath, 'r') as f:
#             content = f.read()
#         # Further processing...
#         if not content:
#             raise ParsingError("File is empty or could not be read.", filename=filepath)
#     except FileNotFoundError:
#         raise FileProcessingError("File not found.", filepath=filepath)
#     except Exception as e:
#         raise FileProcessingError(f"An unexpected error occurred: {e}", filepath=filepath)
