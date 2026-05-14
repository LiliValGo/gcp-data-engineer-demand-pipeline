from pydantic import BaseModel, field_validator, ConfigDict
from datetime import datetime
from typing import Optional, List


class JobV2(BaseModel):
    """
    Enhanced job schema with extraction quality metrics and lineage.
    Current schema version for all new code.

    Schema Version: 2
    Introduced: 2024-03-04
    """

    model_config = ConfigDict(validate_assignment=True)

    # Core job information
    title: str
    company: str
    location: Optional[str] = None
    salary: Optional[str] = None
    url: str
    search_term: str

    # Extracted content
    description: Optional[str] = None
    skills: Optional[List[str]] = None
    experience_level: Optional[str] = None
    contract_type: Optional[str] = None
    job_category: Optional[str] = None

    # Extraction quality metrics
    description_extraction_method: Optional[str] = None
    # "class_search" | "article_tag" | "paragraphs" | "fallback"
    description_confidence: Optional[float] = None  # 0.0 to 1.0
    skills_confidence: Optional[float] = None  # 0.0 to 1.0
    extraction_quality_score: Optional[float] = None  # Overall quality

    # Data validation
    validation_errors: Optional[List[str]] = None
    is_valid: bool = True

    # Metadata
    schema_version: int = 2
    scraped_at: datetime
    processing_timestamp: Optional[datetime] = None

    @field_validator("url", mode="before")
    @classmethod
    def convert_url_to_str(cls, v):
        """Cast HttpUrl to plain string"""
        if v is not None:
            return str(v)
        return v

    @field_validator("description_confidence", "skills_confidence", "extraction_quality_score")
    @classmethod
    def validate_confidence_score(cls, v):
        """Ensure confidence scores are between 0.0 and 1.0"""
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("Confidence score must be between 0.0 and 1.0")
        return v

    def has_quality_issues(self) -> bool:
        """Check if record has quality issues"""
        return bool(self.validation_errors) or not self.is_valid

    def get_quality_score(self) -> float:
        """Get overall quality score"""
        if self.extraction_quality_score is not None:
            return self.extraction_quality_score

        # Calculate from components if not provided
        scores = [
            self.description_confidence or 0.0,
            self.skills_confidence or 0.0,
        ]
        return sum(scores) / len(scores) if scores else 0.0


# Alias for backward compatibility
Job = JobV2