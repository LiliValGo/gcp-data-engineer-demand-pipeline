"""
Tests for scraper/quality.py

What we test:
- Each quality rule individually (RequiredFields, Description, Skills)
- The confidence calculator for descriptions and skills
- The batch validator and its metrics

Lesson: test each rule in isolation before testing the full system.
If the system test fails, you will know exactly which rule is broken.
"""

import pytest

from scraper.quality import (
    DataQualityValidator,
    DataQualityRule,
    RequiredFieldsRule,
    DescriptionQualityRule,
    SkillsQualityRule,
    ExtractionConfidenceCalculator,
    ExtractionMethod,
    QualityMetrics,
)


class TestRequiredFieldsRule:
    """Tests for the required fields rule."""

    def setup_method(self):
        """Runs before each test in this class."""
        self.rule = RequiredFieldsRule(["title", "company", "url", "search_term"])

    def test_passes_when_all_fields_present(self):
        record = {
            "title": "Data Engineer",
            "company": "Acme",
            "url": "https://getonbrd.com/jobs/123",
            "search_term": "data engineer",
        }
        is_valid, error = self.rule.validate(record)
        assert is_valid is True
        assert error is None

    def test_fails_when_title_missing(self):
        record = {"company": "Acme", "url": "https://getonbrd.com/jobs/123", "search_term": "de"}
        is_valid, error = self.rule.validate(record)
        assert is_valid is False
        assert "title" in error

    def test_fails_when_multiple_fields_missing(self):
        record = {"title": "Data Engineer"}
        is_valid, error = self.rule.validate(record)
        assert is_valid is False
        # Error must mention all missing fields
        assert "company" in error
        assert "url" in error

    def test_empty_string_treated_as_missing(self):
        """An empty string must count as a missing field (falsy in Python)."""
        record = {
            "title": "",
            "company": "Acme",
            "url": "https://getonbrd.com/jobs/123",
            "search_term": "de",
        }
        is_valid, error = self.rule.validate(record)
        assert is_valid is False


class TestDescriptionQualityRule:
    """Tests for the description quality rule."""

    def setup_method(self):
        self.rule = DescriptionQualityRule(min_length=50)

    def test_passes_with_good_description(self):
        record = {"description": "This is a valid description that is well over fifty characters long and should pass the rule."}
        is_valid, error = self.rule.validate(record)
        assert is_valid is True

    def test_fails_when_description_missing(self):
        record = {"description": None}
        is_valid, error = self.rule.validate(record)
        assert is_valid is False
        assert "MISSING_DESCRIPTION" in error

    def test_fails_when_description_too_short(self):
        record = {"description": "Short"}
        is_valid, error = self.rule.validate(record)
        assert is_valid is False
        assert "TOO_SHORT" in error

    def test_fails_when_description_has_leading_whitespace(self):
        """A description with leading/trailing spaces must fail."""
        long_desc = "  " + "x" * 100
        record = {"description": long_desc}
        is_valid, error = self.rule.validate(record)
        assert is_valid is False
        assert "WHITESPACE" in error

    def test_exactly_min_length_passes(self):
        """A description of exactly min_length characters must pass."""
        record = {"description": "x" * 50}
        is_valid, error = self.rule.validate(record)
        assert is_valid is True


class TestSkillsQualityRule:
    """Tests for the skills quality rule."""

    def setup_method(self):
        self.rule = SkillsQualityRule(min_skills=1)

    def test_passes_with_skills(self):
        record = {"skills": ["Python", "SQL"]}
        is_valid, error = self.rule.validate(record)
        assert is_valid is True

    def test_fails_when_skills_missing(self):
        record = {"skills": None}
        is_valid, error = self.rule.validate(record)
        assert is_valid is False
        assert "MISSING_SKILLS" in error

    def test_fails_when_skills_empty_list(self):
        record = {"skills": []}
        is_valid, error = self.rule.validate(record)
        assert is_valid is False


class TestExtractionConfidenceCalculator:
    """Tests for the extraction confidence score calculator."""

    def test_score_zero_when_description_none(self):
        score = ExtractionConfidenceCalculator.score_description(
            description=None,
            method=ExtractionMethod.CLASS_SEARCH,
            html_length=5000,
        )
        assert score == 0.0

    def test_class_search_scores_higher_than_fallback(self):
        """CLASS_SEARCH is the most reliable method and must score higher than FALLBACK."""
        desc = "x" * 500

        class_score = ExtractionConfidenceCalculator.score_description(
            description=desc,
            method=ExtractionMethod.CLASS_SEARCH,
            html_length=5000,
        )
        fallback_score = ExtractionConfidenceCalculator.score_description(
            description=desc,
            method=ExtractionMethod.FALLBACK,
            html_length=5000,
        )

        assert class_score > fallback_score

    def test_confidence_score_never_exceeds_1(self):
        """The score must never exceed 1.0 regardless of inputs."""
        score = ExtractionConfidenceCalculator.score_description(
            description="x" * 5000,  # very long description
            method=ExtractionMethod.CLASS_SEARCH,
            html_length=500,
        )
        assert score <= 1.0

    def test_short_description_penalized(self):
        """A description under 50 chars must receive a low score."""
        score = ExtractionConfidenceCalculator.score_description(
            description="short",
            method=ExtractionMethod.CLASS_SEARCH,
            html_length=5000,
        )
        # Base 0.5 + class_search bonus 0.3 - penalty 0.2 = 0.6
        assert score < 0.7

    def test_skills_score_zero_when_none(self):
        score = ExtractionConfidenceCalculator.score_skills(
            skills=None,
            method=ExtractionMethod.CLASS_SEARCH,
        )
        assert score == 0.0

    def test_more_skills_score_higher(self):
        """5+ skills must score higher than 1 skill."""
        many = ExtractionConfidenceCalculator.score_skills(
            skills=["Python", "SQL", "Spark", "dbt", "Airflow"],
            method=ExtractionMethod.CLASS_SEARCH,
        )
        few = ExtractionConfidenceCalculator.score_skills(
            skills=["Python"],
            method=ExtractionMethod.CLASS_SEARCH,
        )
        assert many > few


class TestDataQualityValidator:
    """Tests for the full validator and its batch report."""

    def test_valid_record_passes_all_rules(self, valid_job):
        validator = DataQualityValidator()
        is_valid, errors = validator.validate_record(valid_job.model_dump())
        assert is_valid is True
        assert errors == []

    def test_invalid_record_collects_multiple_errors(self, invalid_job):
        validator = DataQualityValidator()
        is_valid, errors = validator.validate_record(invalid_job.model_dump())
        assert is_valid is False
        # Must fail for at least description and skills
        assert len(errors) >= 2

    def test_batch_metrics_correct_counts(self, job_batch, validator):
        report = validator.validate_batch(job_batch)

        # job_batch has 1 valid (valid_job) and 1 invalid (invalid_job)
        assert report.metrics.total_records == 2
        assert report.metrics.valid_records == 1
        assert report.metrics.invalid_records == 1

    def test_batch_null_rates_between_0_and_1(self, job_batch, validator):
        report = validator.validate_batch(job_batch)
        assert 0.0 <= report.metrics.null_description_rate <= 1.0
        assert 0.0 <= report.metrics.null_salary_rate <= 1.0
        assert 0.0 <= report.metrics.null_location_rate <= 1.0

    def test_batch_empty_list_does_not_crash(self, validator):
        """Validating an empty list must not raise an exception."""
        report = validator.validate_batch([])
        assert report.metrics.total_records == 0
        assert report.metrics.avg_confidence == 0.0

    def test_quality_report_to_dict(self, job_batch, validator):
        report = validator.validate_batch(job_batch)
        result = report.to_dict()
        assert "valid_count" in result
        assert "invalid_count" in result
        assert "metrics" in result
