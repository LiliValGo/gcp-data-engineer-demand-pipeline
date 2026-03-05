from typing import List, Optional
import logging
from pydantic_settings import BaseSettings
from pydantic import Field


class ScraperSettings(BaseSettings):
    """Configuration for the web scraper, loaded from environment variables and .env file"""

    # Scraping behavior
    base_url: str = Field(
        default="https://www.getonbrd.com/jobs",
        description="Base URL for job postings"
    )
    search_terms: List[str] = Field(
        default=[
            "data engineer",
            "ingeniero de datos",
            "analytics engineer",
            "big data engineer",
            "etl developer",
        ],
        description="Search terms for job queries"
    )
    timeout: int = Field(
        default=10,
        description="HTTP request timeout in seconds"
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of retry attempts"
    )
    delay_between_requests: float = Field(
        default=1.5,
        description="Delay between requests in seconds"
    )
    headless: bool = Field(
        default=True,
        description="Run browser in headless mode"
    )
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        description="User-Agent header for requests"
    )

    # Environment configuration
    environment: str = Field(
        default="development",
        description="Deployment environment (development, staging, production)"
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )
    log_format: str = Field(
        default="json",
        description="Log format (json or text)"
    )

    # GCP configuration (optional)
    gcp_project: Optional[str] = Field(
        default=None,
        description="GCP project ID"
    )
    bigquery_dataset: Optional[str] = Field(
        default=None,
        description="BigQuery dataset name"
    )

    # Web app configuration
    fastapi_host: str = Field(
        default="0.0.0.0",
        description="FastAPI server host"
    )
    fastapi_port: int = Field(
        default=8000,
        description="FastAPI server port"
    )
    fastapi_reload: bool = Field(
        default=True,
        description="Enable FastAPI auto-reload"
    )

    class Config:
        env_file = ".env"
        case_sensitive = False

    def get_log_level_int(self) -> int:
        """Convert log level string to logging module integer"""
        return getattr(logging, self.log_level.upper(), logging.INFO)


# Global settings instance
settings = ScraperSettings()