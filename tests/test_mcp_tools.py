"""
Tests for mcp_server/queries.py

What we test:
- get_available_roles  — returns list with canonical_role + total_jobs
- get_top_skills       — sorted by mention_count, limit respected
- get_demand_trends    — returns dates and job counts for the role
- get_salary_trends    — returns salary stats; city filter works
- compare_skills       — full match, no match, partial match, case-insensitive

Fixtures:
  pipeline_with_data  — MedallionPipeline backed by an in-memory DuckDB
                        with pre-populated silver.jobs and Gold tables.

Notes:
- Tests call the query functions in mcp_server.queries directly.
  No MCP protocol is involved (that layer is trivially thin in server.py).
- compare_skills tests mock get_top_skills so they are pure unit tests
  independent of the database state.
"""

import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import patch

import mcp_server.queries as queries


# ---------------------------------------------------------------------------
# Fixture — populated DuckDB
# ---------------------------------------------------------------------------

def _make_silver_rows() -> list[dict]:
    """
    Seven minimal silver.jobs rows covering two roles, two dates, and
    a range of salaries/cities — enough to exercise all four query functions.
    """
    date1 = datetime(2026, 4, 15, 10, 0, 0)
    date2 = datetime(2026, 4, 16, 10, 0, 0)
    now = datetime(2026, 4, 18, 0, 0, 0)

    return [
        # ----------- data_engineer (5 jobs) -----------
        {
            "job_id": "de_001",
            "url": "https://getonbrd.com/jobs/de-001",
            "title": "Data Engineer",
            "company": "Corp A",
            "canonical_role": "data_engineer",
            "search_term": "data engineer",
            "location": "Santiago, Chile",
            "city": "Santiago",
            "is_remote": False,
            "salary_raw": "USD 80,000 - 120,000",
            "salary_usd_min": 80000.0,
            "salary_usd_max": 120000.0,
            "description": "Build pipelines",
            "skills": ["python", "sql", "spark"],
            "experience_level": "mid",
            "contract_type": "full-time",
            "job_category": "Data",
            "extraction_quality_score": 0.9,
            "scraped_at": date1,
            "processing_timestamp": now,
            "bronze_file_path": "bronze/de-001.parquet",
        },
        {
            "job_id": "de_002",
            "url": "https://getonbrd.com/jobs/de-002",
            "title": "Senior Data Engineer",
            "company": "Corp B",
            "canonical_role": "data_engineer",
            "search_term": "data engineer",
            "location": "Remote",
            "city": None,
            "is_remote": True,
            "salary_raw": "USD 90,000 - 130,000",
            "salary_usd_min": 90000.0,
            "salary_usd_max": 130000.0,
            "description": "Build pipelines",
            "skills": ["python", "dbt", "kafka"],
            "experience_level": "senior",
            "contract_type": "full-time",
            "job_category": "Data",
            "extraction_quality_score": 0.85,
            "scraped_at": date1,
            "processing_timestamp": now,
            "bronze_file_path": "bronze/de-002.parquet",
        },
        {
            "job_id": "de_003",
            "url": "https://getonbrd.com/jobs/de-003",
            "title": "Data Engineer",
            "company": "Corp C",
            "canonical_role": "data_engineer",
            "search_term": "data engineer",
            "location": "Santiago, Chile",
            "city": "Santiago",
            "is_remote": False,
            "salary_raw": "USD 85,000 - 125,000",
            "salary_usd_min": 85000.0,
            "salary_usd_max": 125000.0,
            "description": "Build pipelines",
            "skills": ["python", "sql", "airflow"],
            "experience_level": "mid",
            "contract_type": "full-time",
            "job_category": "Data",
            "extraction_quality_score": 0.88,
            "scraped_at": date2,
            "processing_timestamp": now,
            "bronze_file_path": "bronze/de-003.parquet",
        },
        {
            "job_id": "de_004",
            "url": "https://getonbrd.com/jobs/de-004",
            "title": "Data Engineer",
            "company": "Corp D",
            "canonical_role": "data_engineer",
            "search_term": "data engineer",
            "location": "Remote",
            "city": None,
            "is_remote": True,
            "salary_raw": None,
            "salary_usd_min": None,
            "salary_usd_max": None,
            "description": "Build pipelines",
            "skills": ["python", "spark", "kafka"],
            "experience_level": "mid",
            "contract_type": "full-time",
            "job_category": "Data",
            "extraction_quality_score": 0.80,
            "scraped_at": date2,
            "processing_timestamp": now,
            "bronze_file_path": "bronze/de-004.parquet",
        },
        {
            "job_id": "de_005",
            "url": "https://getonbrd.com/jobs/de-005",
            "title": "Data Engineer",
            "company": "Corp E",
            "canonical_role": "data_engineer",
            "search_term": "data engineer",
            "location": "Buenos Aires",
            "city": "Buenos Aires",
            "is_remote": False,
            "salary_raw": None,
            "salary_usd_min": None,
            "salary_usd_max": None,
            "description": "Build pipelines",
            "skills": ["python", "sql"],
            "experience_level": "junior",
            "contract_type": "full-time",
            "job_category": "Data",
            "extraction_quality_score": 0.75,
            "scraped_at": date2,
            "processing_timestamp": now,
            "bronze_file_path": "bronze/de-005.parquet",
        },
        # ----------- data_analyst (2 jobs) -----------
        {
            "job_id": "da_001",
            "url": "https://getonbrd.com/jobs/da-001",
            "title": "Data Analyst",
            "company": "Corp F",
            "canonical_role": "data_analyst",
            "search_term": "data analyst",
            "location": "Santiago, Chile",
            "city": "Santiago",
            "is_remote": False,
            "salary_raw": "USD 40,000 - 60,000",
            "salary_usd_min": 40000.0,
            "salary_usd_max": 60000.0,
            "description": "Analyze data",
            "skills": ["sql", "excel"],
            "experience_level": "mid",
            "contract_type": "full-time",
            "job_category": "Data",
            "extraction_quality_score": 0.82,
            "scraped_at": date1,
            "processing_timestamp": now,
            "bronze_file_path": "bronze/da-001.parquet",
        },
        {
            "job_id": "da_002",
            "url": "https://getonbrd.com/jobs/da-002",
            "title": "Sr Data Analyst",
            "company": "Corp G",
            "canonical_role": "data_analyst",
            "search_term": "data analyst",
            "location": "Santiago, Chile",
            "city": "Santiago",
            "is_remote": False,
            "salary_raw": "USD 50,000 - 70,000",
            "salary_usd_min": 50000.0,
            "salary_usd_max": 70000.0,
            "description": "Analyze data",
            "skills": ["sql", "tableau"],
            "experience_level": "senior",
            "contract_type": "full-time",
            "job_category": "Data",
            "extraction_quality_score": 0.88,
            "scraped_at": date1,
            "processing_timestamp": now,
            "bronze_file_path": "bronze/da-002.parquet",
        },
    ]


@pytest.fixture()
def db_pipeline(tmp_path):
    """
    Yields a MedallionPipeline backed by a fresh tmp DuckDB, pre-populated
    with silver.jobs rows and Gold tables. Resets the queries singleton
    before and after.
    """
    queries.reset_pipeline()

    db_path = str(tmp_path / "test_mcp.duckdb")
    pipeline = queries.get_pipeline(db_path=db_path)

    # Insert silver rows via a registered DataFrame
    rows = _make_silver_rows()
    df = pd.DataFrame(rows)
    pipeline.conn.register("_test_silver", df)
    pipeline.conn.execute("""
        INSERT INTO silver.jobs
        SELECT
            job_id, url, title, company, canonical_role, search_term,
            location, city, is_remote, salary_raw, salary_usd_min,
            salary_usd_max, description, skills, experience_level,
            contract_type, job_category, extraction_quality_score,
            TRY_CAST(scraped_at AS TIMESTAMP),
            TRY_CAST(processing_timestamp AS TIMESTAMP),
            bronze_file_path
        FROM _test_silver
    """)
    pipeline.conn.unregister("_test_silver")

    # Build Gold tables from the inserted Silver data
    pipeline.run_silver_to_gold()

    yield pipeline

    queries.reset_pipeline()


# ---------------------------------------------------------------------------
# Tests — get_available_roles
# ---------------------------------------------------------------------------

def test_get_available_roles_returns_list(db_pipeline):
    result = queries.get_available_roles()

    assert isinstance(result, list)
    assert len(result) == 2

    roles = {r["canonical_role"] for r in result}
    assert "data_engineer" in roles
    assert "data_analyst" in roles


def test_get_available_roles_job_counts(db_pipeline):
    result = queries.get_available_roles()

    counts = {r["canonical_role"]: r["total_jobs"] for r in result}
    assert counts["data_engineer"] == 5
    assert counts["data_analyst"] == 2


# ---------------------------------------------------------------------------
# Tests — get_top_skills
# ---------------------------------------------------------------------------

def test_get_top_skills_returns_sorted_by_count(db_pipeline):
    result = queries.get_top_skills("data_engineer")

    assert isinstance(result, list)
    assert len(result) > 0

    # python appears in all 5 DE jobs → must be first
    assert result[0]["skill"] == "python"
    assert result[0]["mention_count"] == 5

    # Result must be sorted descending
    counts = [r["mention_count"] for r in result]
    assert counts == sorted(counts, reverse=True)


def test_get_top_skills_respects_limit(db_pipeline):
    result = queries.get_top_skills("data_engineer", limit=2)

    assert len(result) == 2


def test_get_top_skills_empty_for_unknown_role(db_pipeline):
    result = queries.get_top_skills("nonexistent_role")

    assert result == []


# ---------------------------------------------------------------------------
# Tests — get_demand_trends
# ---------------------------------------------------------------------------

def test_get_demand_trends_returns_dates(db_pipeline):
    result = queries.get_demand_trends("data_engineer")

    assert isinstance(result, list)
    # Two distinct dates in fixture (2026-04-15 and 2026-04-16)
    assert len(result) == 2


def test_get_demand_trends_ordered_desc(db_pipeline):
    result = queries.get_demand_trends("data_engineer")

    dates = [r["date"] for r in result]
    assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# Tests — get_salary_trends
# ---------------------------------------------------------------------------

def test_get_salary_trends_no_city_filter(db_pipeline):
    result = queries.get_salary_trends("data_engineer")

    assert isinstance(result, list)
    # Should have entries for Santiago and Remote/Unknown
    cities = {r["city"] for r in result}
    assert "Santiago" in cities


def test_get_salary_trends_with_city_filter(db_pipeline):
    result = queries.get_salary_trends("data_engineer", city="Santiago")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["city"] == "Santiago"
    # Two Santiago jobs (de_001 and de_003) both have salary
    assert result[0]["jobs_with_salary"] == 2


# ---------------------------------------------------------------------------
# Tests — compare_skills (mocked get_top_skills → pure unit tests)
# ---------------------------------------------------------------------------

_MOCK_DEMANDED = [
    {"skill": "python", "mention_count": 5, "pct": 50.0},
    {"skill": "sql", "mention_count": 3, "pct": 30.0},
]


def test_compare_skills_full_match():
    with patch("mcp_server.queries.get_top_skills", return_value=_MOCK_DEMANDED):
        result = queries.compare_skills(["python", "sql"], "data_engineer")

    assert sorted(result["skills_you_have"]) == ["python", "sql"]
    assert result["skills_missing"] == []
    assert result["additional_skills"] == []
    assert result["market_coverage_pct"] == 100.0


def test_compare_skills_no_match():
    with patch("mcp_server.queries.get_top_skills", return_value=_MOCK_DEMANDED):
        result = queries.compare_skills(["excel"], "data_engineer")

    assert result["skills_you_have"] == []
    assert sorted(result["skills_missing"]) == ["python", "sql"]
    assert result["additional_skills"] == ["excel"]
    assert result["market_coverage_pct"] == 0.0


def test_compare_skills_partial_match_calculates_coverage():
    with patch("mcp_server.queries.get_top_skills", return_value=_MOCK_DEMANDED):
        result = queries.compare_skills(["python", "excel"], "data_engineer")

    assert result["skills_you_have"] == ["python"]
    assert result["skills_missing"] == ["sql"]
    assert result["additional_skills"] == ["excel"]
    assert result["market_coverage_pct"] == 50.0


def test_compare_skills_case_insensitive():
    with patch("mcp_server.queries.get_top_skills", return_value=_MOCK_DEMANDED):
        result = queries.compare_skills(["Python", "SQL"], "data_engineer")

    assert sorted(result["skills_you_have"]) == ["python", "sql"]
    assert result["market_coverage_pct"] == 100.0


def test_compare_skills_no_demand_data():
    with patch("mcp_server.queries.get_top_skills", return_value=[]):
        result = queries.compare_skills(["python", "sql"], "unknown_role")

    assert result["skills_you_have"] == []
    assert result["skills_missing"] == []
    assert result["market_coverage_pct"] == 0.0
