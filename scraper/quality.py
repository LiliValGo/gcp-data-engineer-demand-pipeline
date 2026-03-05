"""Data quality framework for job scraping"""

from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ExtractionMethod(str, Enum):
    """Enum for extraction methods"""

    CLASS_SEARCH = "class_search"
    ARTICLE_TAG = "article_tag"
    PARAGRAPHS = "paragraphs"
    FALLBACK = "fallback"


@dataclass
class ExtractionConfidence:
    """Confidence scores for extraction operations"""

    method: ExtractionMethod
    confidence: float  # 0.0 to 1.0
    text_length: int
    details: Optional[Dict[str, Any]] = None

    def is_high_confidence(self, threshold: float = 0.7) -> bool:
        """Check if confidence exceeds threshold"""
        return self.confidence >= threshold


@dataclass
class QualityMetrics:
    """Overall quality metrics for a dataset"""

    total_records: int
    valid_records: int
    invalid_records: int
    records_with_description: int
    records_with_skills: int
    records_with_experience: int
    avg_confidence: float
    null_description_rate: float
    null_location_rate: float
    null_salary_rate: float

    def __repr__(self) -> str:
        return (
            f"QualityMetrics(total={self.total_records}, "
            f"valid={self.valid_records}, "
            f"avg_confidence={self.avg_confidence:.2f})"
        )


class ExtractionConfidenceCalculator:
    """Calculate confidence scores for extractions"""

    @staticmethod
    def score_description(
        description: Optional[str],
        method: ExtractionMethod,
        html_length: int,
    ) -> float:
        """
        Calculate confidence score for description extraction.

        Args:
            description: Extracted description text
            method: Extraction method used
            html_length: Length of HTML page

        Returns:
            Confidence score (0.0 to 1.0)
        """
        if not description:
            return 0.0

        score = 0.5  # Base score

        # Method bonus
        method_bonus = {
            ExtractionMethod.CLASS_SEARCH: 0.3,  # Most reliable
            ExtractionMethod.ARTICLE_TAG: 0.2,
            ExtractionMethod.PARAGRAPHS: 0.1,
            ExtractionMethod.FALLBACK: 0.05,
        }
        score += method_bonus.get(method, 0.0)

        # Length bonus (characteristics of good descriptions)
        desc_len = len(description)
        if desc_len > 1000:
            score += 0.15
        elif desc_len > 500:
            score += 0.1
        elif desc_len < 50:
            score -= 0.2

        # Ratio bonus (description vs HTML)
        ratio = desc_len / max(html_length, 1)
        if 0.1 < ratio < 0.5:  # Reasonable proportion
            score += 0.05

        return min(score, 1.0)

    @staticmethod
    def score_skills(
        skills: Optional[List[str]],
        method: ExtractionMethod,
    ) -> float:
        """Calculate confidence score for skills extraction"""
        if not skills:
            return 0.0

        score = 0.5

        # Method bonus
        method_bonus = {
            ExtractionMethod.CLASS_SEARCH: 0.35,
            ExtractionMethod.ARTICLE_TAG: 0.15,
            ExtractionMethod.FALLBACK: 0.1,
        }
        score += method_bonus.get(method, 0.0)

        # Count bonus (more skills = more reliable)
        if len(skills) >= 5:
            score += 0.1
        elif len(skills) < 2:
            score -= 0.1

        return min(score, 1.0)


class DataQualityRule:
    """Base class for data quality rules"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.violations = []

    def validate(self, record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate a single record.

        Returns:
            (is_valid, error_message)
        """
        raise NotImplementedError


class DescriptionQualityRule(DataQualityRule):
    """Rule: Description must exist and have minimum length"""

    def __init__(self, min_length: int = 50):
        super().__init__(
            "description_quality",
            f"Description must be present and at least {min_length} characters",
        )
        self.min_length = min_length

    def validate(self, record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        description = record.get("description")

        if not description:
            return False, "MISSING_DESCRIPTION"

        if len(description) < self.min_length:
            return False, f"DESCRIPTION_TOO_SHORT (length={len(description)})"

        if len(description.strip()) != len(description):
            return False, "DESCRIPTION_HAS_WHITESPACE"

        return True, None


class SkillsQualityRule(DataQualityRule):
    """Rule: Skills should be present"""

    def __init__(self, min_skills: int = 1):
        super().__init__(
            "skills_quality",
            f"Record should have at least {min_skills} skill(s)",
        )
        self.min_skills = min_skills

    def validate(self, record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        skills = record.get("skills")

        if not skills:
            return False, "MISSING_SKILLS"

        if len(skills) < self.min_skills:
            return False, f"INSUFFICIENT_SKILLS (count={len(skills)})"

        return True, None


class RequiredFieldsRule(DataQualityRule):
    """Rule: Required fields must be present"""

    def __init__(self, required_fields: List[str]):
        super().__init__(
            "required_fields",
            f"Must contain fields: {', '.join(required_fields)}",
        )
        self.required_fields = required_fields

    def validate(self, record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        missing = [f for f in self.required_fields if not record.get(f)]

        if missing:
            return False, f"MISSING_FIELDS: {', '.join(missing)}"

        return True, None


class DataQualityValidator:
    """Validates data quality against a set of rules"""

    def __init__(self, rules: Optional[List[DataQualityRule]] = None):
        self.rules = rules or self._get_default_rules()

    @staticmethod
    def _get_default_rules() -> List[DataQualityRule]:
        """Get default QA rules"""
        return [
            RequiredFieldsRule(["title", "company", "url", "search_term"]),
            DescriptionQualityRule(min_length=50),
            SkillsQualityRule(min_skills=1),
        ]

    def validate_record(self, record: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate a single record against all rules.

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []

        for rule in self.rules:
            is_valid, error_msg = rule.validate(record)
            if not is_valid:
                errors.append(f"{rule.name}: {error_msg}")

        return len(errors) == 0, errors

    def validate_batch(
        self, records: List[Dict[str, Any]]
    ) -> "QualityReport":
        """
        Validate multiple records and generate report.

        Returns:
            QualityReport with metrics
        """
        valid_records = []
        invalid_records = []

        for record in records:
            is_valid, errors = self.validate_record(record)
            if is_valid:
                valid_records.append(record)
            else:
                invalid_records.append(
                    {
                        "record": record,
                        "errors": errors,
                    }
                )

        # Calculate metrics
        total = len(records)
        valid = len(valid_records)

        with_description = len(
            [r for r in records if r.get("description")]
        )
        with_skills = len([r for r in records if r.get("skills")])
        with_experience = len(
            [r for r in records if r.get("experience_level")]
        )

        null_location_rate = len(
            [r for r in records if not r.get("location")]
        ) / max(total, 1)
        null_salary_rate = len(
            [r for r in records if not r.get("salary")]
        ) / max(total, 1)
        null_description_rate = len(
            [r for r in records if not r.get("description")]
        ) / max(total, 1)

        avg_confidence = (
            sum(
                r.get("description_confidence") or 0.0 for r in records
            )
            / max(total, 1)
        )

        metrics = QualityMetrics(
            total_records=total,
            valid_records=valid,
            invalid_records=len(invalid_records),
            records_with_description=with_description,
            records_with_skills=with_skills,
            records_with_experience=with_experience,
            avg_confidence=avg_confidence,
            null_description_rate=null_description_rate,
            null_location_rate=null_location_rate,
            null_salary_rate=null_salary_rate,
        )

        return QualityReport(
            valid_records=valid_records,
            invalid_records=invalid_records,
            metrics=metrics,
        )


@dataclass
class QualityReport:
    """Report of quality validation results"""

    valid_records: List[Dict[str, Any]]
    invalid_records: List[Dict[str, Any]]
    metrics: QualityMetrics

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid_count": len(self.valid_records),
            "invalid_count": len(self.invalid_records),
            "metrics": asdict(self.metrics),
        }

    def __repr__(self) -> str:
        return (
            f"QualityReport(valid={len(self.valid_records)}, "
            f"invalid={len(self.invalid_records)}, "
            f"avg_confidence={self.metrics.avg_confidence:.2f})"
        )
