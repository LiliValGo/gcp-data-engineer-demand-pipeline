"""
Tests for scraper/models.py

What we test and why:
- Valid creation: verify the model accepts correct data
- Field validators: description_confidence must reject values outside [0, 1]
- Business methods: has_quality_issues() and get_quality_score()
- Backward compat: 'Job' must be an alias for JobV2

Pattern used: AAA (Arrange - Act - Assert)
  Arrange: prepare the input data
  Act:     call the function under test
  Assert:  verify the expected result
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from scraper.models import JobV2, Job


class TestJobV2Creation:
    """Tests for model instantiation."""

    def test_create_minimal_valid_job(self):
        """A job with only required fields should be created without errors."""
        # Arrange & Act
        job = JobV2(
            title="Data Engineer",
            company="Acme Corp",
            url="https://www.getonbrd.com/jobs/de-123",
            search_term="data engineer",
            scraped_at=datetime.now(),
        )

        # Assert
        assert job.title == "Data Engineer"
        assert job.company == "Acme Corp"
        assert job.is_valid is True       # default
        assert job.schema_version == 2    # always V2

    def test_create_complete_job(self, valid_job):
        """A complete job (from fixture) should have all fields accessible."""
        assert valid_job.skills == ["Python", "Apache Spark", "AWS", "dbt", "SQL", "Airflow"]
        assert valid_job.experience_level == "senior"
        assert valid_job.schema_version == 2

    def test_url_is_always_string(self):
        """The url validator must cast any value to str."""
        job = JobV2(
            title="Test",
            company="Test Co",
            url="https://getonbrd.com/jobs/123",
            search_term="test",
            scraped_at=datetime.now(),
        )
        assert isinstance(job.url, str)


class TestJobV2ConfidenceValidation:
    """Tests for confidence score field validators."""

    @pytest.mark.parametrize("score", [0.0, 0.5, 1.0])
    def test_valid_confidence_scores(self, score):
        """Scores between 0.0 and 1.0 are valid."""
        job = JobV2(
            title="Test",
            company="Test Co",
            url="https://getonbrd.com/jobs/123",
            search_term="test",
            scraped_at=datetime.now(),
            description_confidence=score,
        )
        assert job.description_confidence == score

    @pytest.mark.parametrize("bad_score", [-0.1, 1.1, 2.0, -1.0])
    def test_invalid_confidence_scores_raise_error(self, bad_score):
        """Scores outside [0, 1] must raise a pydantic ValidationError."""
        with pytest.raises(ValidationError):
            JobV2(
                title="Test",
                company="Test Co",
                url="https://getonbrd.com/jobs/123",
                search_term="test",
                scraped_at=datetime.now(),
                description_confidence=bad_score,
            )


class TestJobV2QualityMethods:
    """Tests for quality-related business methods."""

    def test_has_quality_issues_when_invalid(self, invalid_job):
        """A job marked is_valid=False must report quality issues."""
        invalid_job.is_valid = False
        assert invalid_job.has_quality_issues() is True

    def test_has_quality_issues_when_has_errors(self, valid_job):
        """A job with validation_errors must report quality issues."""
        valid_job.validation_errors = ["required_fields: MISSING_DESCRIPTION"]
        assert valid_job.has_quality_issues() is True

    def test_no_quality_issues_on_clean_job(self, valid_job):
        """A clean job with no errors must not report issues."""
        assert valid_job.has_quality_issues() is False

    def test_get_quality_score_uses_extraction_score_when_present(self, valid_job):
        """If extraction_quality_score is set, that value must be returned."""
        valid_job.extraction_quality_score = 0.95
        assert valid_job.get_quality_score() == 0.95

    def test_get_quality_score_calculates_avg_when_no_extraction_score(self):
        """Without extraction_quality_score, returns average of description + skills confidence."""
        job = JobV2(
            title="Test",
            company="Test Co",
            url="https://getonbrd.com/jobs/123",
            search_term="test",
            scraped_at=datetime.now(),
            description_confidence=0.8,
            skills_confidence=0.6,
            extraction_quality_score=None,
        )
        # Expected average of 0.8 and 0.6 = 0.7
        assert job.get_quality_score() == pytest.approx(0.7)

    def test_get_quality_score_returns_zero_with_no_confidence_data(self):
        """With no confidence data at all, the score must be 0.0."""
        job = JobV2(
            title="Test",
            company="Test Co",
            url="https://getonbrd.com/jobs/123",
            search_term="test",
            scraped_at=datetime.now(),
        )
        assert job.get_quality_score() == 0.0


class TestBackwardCompatibility:
    """Tests for legacy code compatibility."""

    def test_job_alias_is_jobv2(self):
        """'Job' must be exactly the same type as JobV2."""
        assert Job is JobV2
