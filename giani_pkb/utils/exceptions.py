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
