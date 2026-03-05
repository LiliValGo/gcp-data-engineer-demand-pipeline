"""Exception hierarchy for scraper module"""


class ScraperException(Exception):
    """Base exception for all scraper-related errors"""

    pass


class ClientException(ScraperException):
    """Exception raised by web client operations"""

    def __init__(
        self,
        message: str,
        url: str = None,
        status_code: int = None,
        original_error: Exception = None,
    ):
        self.message = message
        self.url = url
        self.status_code = status_code
        self.original_error = original_error
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        msg = self.message
        if self.url:
            msg += f" (URL: {self.url})"
        if self.status_code:
            msg += f" [Status: {self.status_code}]"
        if self.original_error:
            msg += f" - {str(self.original_error)}"
        return msg


class ExtractionException(ScraperException):
    """Exception raised during data extraction"""

    def __init__(
        self,
        extraction_type: str,
        url: str,
        original_error: Exception = None,
    ):
        self.extraction_type = extraction_type
        self.url = url
        self.original_error = original_error
        message = (
            f"Failed to extract {extraction_type} from {url}"
        )
        if original_error:
            message += f": {str(original_error)}"
        super().__init__(message)


class CheckpointException(ScraperException):
    """Exception raised by checkpoint/idempotency operations"""

    pass


class QualityException(ScraperException):
    """Exception raised during data quality validation"""

    def __init__(self, rule_name: str, message: str, record_id: str = None):
        self.rule_name = rule_name
        self.record_id = record_id
        msg = f"Quality rule '{rule_name}' failed"
        if record_id:
            msg += f" for record {record_id}"
        msg += f": {message}"
        super().__init__(msg)


class ConfigException(ScraperException):
    """Exception raised during configuration loading/validation"""

    pass


class ValidationException(ScraperException):
    """Exception raised during data validation"""

    def __init__(self, field: str, value: str, message: str):
        self.field = field
        self.value = value
        super().__init__(f"Validation failed for field '{field}': {message}")
