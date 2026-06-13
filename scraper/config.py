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
            # Data Engineering & Analytics
            "data engineer",
            "ingeniero de datos",
            "analytics engineer",
            "ingeniero de analytics",
            "big data engineer",
            "big data engineer",
            "etl developer",
            "desarrollador etl",
            "data analyst",
            "analista de datos",

            # Machine Learning & AI (Trending 2025-2026)
            "machine learning engineer",
            "ingeniero machine learning",
            "ml engineer",
            "ai engineer",
            "ingeniero ia",
            "ai prompt engineer",
            "ingeniero de prompts ia",
            "llm engineer",
            "data scientist",
            "científico de datos",

            # Cloud & Infrastructure
            "cloud architect",
            "arquitecto de nube",
            "cloud engineer",
            "ingeniero de nube",
            "aws engineer",
            "ingeniero aws",
            "gcp engineer",
            "ingeniero gcp",
            "azure engineer",
            "ingeniero azure",
            "devops engineer",
            "ingeniero devops",
            "infrastructure engineer",
            "ingeniero de infraestructura",
            "site reliability engineer",
            "sre engineer",

            # Backend & Full Stack Development
            "backend developer",
            "desarrollador backend",
            "backend engineer",
            "ingeniero backend",
            "full stack developer",
            "desarrollador full stack",
            "api developer",
            "desarrollador api",

            # Frontend Development
            "frontend developer",
            "desarrollador frontend",
            "frontend engineer",
            "ingeniero frontend",
            "react developer",
            "desarrollador react",

            # Security & Compliance
            "security engineer",
            "ingeniero de seguridad",
            "cloud security engineer",
            "ingeniero de seguridad en nube",

            # Architecture & Strategy
            "solutions architect",
            "arquitecto de soluciones",
            "technical architect",
            "arquitecto técnico",
            "software architect",
            "arquitecto de software",

            # Data & BI Platforms
            "bi developer",
            "desarrollador de bi",
            "tableau developer",
            "desarrollador tableau",
            "power bi developer",
            "desarrollador power bi",
            "dbt developer",
            "desarrollador dbt",

            # Leadership & Management
            "engineering manager",
            "gerente de ingeniería",
            "tech lead",
            "líder técnico",
            "product manager",
            "gerente de producto",
        ],
        description="Search terms for job queries - Tech roles 2025-2026"
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

    # Google Gemini API (optional)
    google_api_key: Optional[str] = Field(
        default=None,
        description="Google API key for Gemini (used to generate role variants)"
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