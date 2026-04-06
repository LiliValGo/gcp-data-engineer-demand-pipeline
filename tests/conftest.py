"""
Shared fixtures for all project tests.

What is a pytest fixture?
A fixture is a function that prepares data or resources that tests need.
Pytest automatically injects them by name into test parameters.
The 'scope' parameter defines how long the fixture lives:
  - "function" (default): recreated for each test — use for mutable data
  - "module": created once per file — use for expensive-to-initialize objects
  - "session": created once for the entire test session
"""

import pytest
from datetime import datetime

from scraper.models import JobV2
from scraper.quality import DataQualityValidator, ExtractionMethod


# ---------------------------------------------------------------------------
# Data fixtures (scope="function" — recreated for each test)
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_job() -> JobV2:
    """Valid job with all required fields and high quality scores."""
    return JobV2(
        title="Senior Data Engineer",
        company="TechCorp LATAM",
        url="https://www.getonbrd.com/jobs/data-engineer-techcorp-123",
        search_term="data engineer",
        location="Remote",
        salary="USD 100,000 - 140,000",
        description="We are looking for a Data Engineer with experience in Apache Spark, "
                    "AWS Glue and dbt to design scalable data pipelines. "
                    "You will work with datasets of millions of records daily. "
                    "Strong skills in Python, advanced SQL and clean code practices required.",
        skills=["Python", "Apache Spark", "AWS", "dbt", "SQL", "Airflow"],
        experience_level="senior",
        contract_type="full-time",
        job_category="Data Engineering",
        description_extraction_method="class_search",
        description_confidence=0.92,
        skills_confidence=0.88,
        extraction_quality_score=0.90,
        is_valid=True,
        scraped_at=datetime(2026, 3, 28, 10, 0, 0),
    )


@pytest.fixture
def invalid_job() -> JobV2:
    """Minimal job — no description or skills (fails quality rules)."""
    return JobV2(
        title="Data Analyst",
        company="Analytics Co",
        url="https://www.getonbrd.com/jobs/data-analyst-123",
        search_term="data analyst",
        description=None,
        skills=None,
        scraped_at=datetime(2026, 3, 28, 11, 0, 0),
    )


@pytest.fixture
def job_batch(valid_job, invalid_job) -> list:
    """
    Mixed batch of jobs for batch validation testing.
    Reuses valid_job and invalid_job fixtures — pytest injects them automatically.
    """
    return [valid_job.model_dump(), invalid_job.model_dump()]


@pytest.fixture
def validator() -> DataQualityValidator:
    """Validator with default quality rules."""
    return DataQualityValidator()
