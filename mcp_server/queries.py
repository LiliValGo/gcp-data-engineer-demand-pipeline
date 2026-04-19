"""
DuckDB query functions for the MCP Server.

Each function is a thin wrapper over the existing MedallionPipeline,
querying the Gold (and Silver) layers and returning JSON-serializable
list[dict] or dict structures ready for FastMCP tool responses.

Singleton pattern:
    The MedallionPipeline (and its DuckDB connection) is created once and
    reused across all tool calls. Tests can override it via reset_pipeline()
    followed by get_pipeline(db_path=...).
"""

from __future__ import annotations

import logging
from typing import Optional

from scraper.medallion import MedallionPipeline

logger = logging.getLogger(__name__)

_pipeline: Optional[MedallionPipeline] = None


def get_pipeline(db_path: str = "data/pipeline.duckdb") -> MedallionPipeline:
    """Return the singleton MedallionPipeline; creates it on the first call."""
    global _pipeline
    if _pipeline is None:
        _pipeline = MedallionPipeline(duckdb_path=db_path)
    return _pipeline


def reset_pipeline() -> None:
    """Close and discard the singleton. Used in tests to get a fresh DB."""
    global _pipeline
    if _pipeline is not None:
        _pipeline.close()
    _pipeline = None


# ---------------------------------------------------------------------------
# Tool 1 — available roles
# ---------------------------------------------------------------------------

def get_available_roles() -> list[dict]:
    """
    List all canonical roles with their total job count.

    Queries silver.jobs directly so the result reflects the full
    deduplicated dataset, not just what made it into Gold aggregations.
    """
    conn = get_pipeline().conn
    df = conn.execute("""
        SELECT
            canonical_role,
            COUNT(*) AS total_jobs
        FROM silver.jobs
        GROUP BY canonical_role
        ORDER BY total_jobs DESC
    """).df()
    return df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# Tool 2 — top skills
# ---------------------------------------------------------------------------

def get_top_skills(role: str, limit: int = 20) -> list[dict]:
    """
    Return the most demanded skills for a role, ordered by mention count.

    Column 'pct' is the percentage of jobs for that role that mention the skill.
    Uses parameterized query to prevent SQL injection.
    """
    conn = get_pipeline().conn
    df = conn.execute(
        """
        SELECT
            skill,
            mention_count,
            pct_of_role_jobs AS pct
        FROM gold.skills_frequency
        WHERE canonical_role = ?
        ORDER BY mention_count DESC
        LIMIT ?
        """,
        [role, limit],
    ).df()
    return df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# Tool 3 — demand trends
# ---------------------------------------------------------------------------

def get_demand_trends(role: str) -> list[dict]:
    """
    Return daily job demand for a role over the last 30 days.

    Returns date as ISO string (YYYY-MM-DD) so it is directly JSON-serialisable.
    """
    conn = get_pipeline().conn
    df = conn.execute(
        """
        SELECT
            CAST(date AS VARCHAR)  AS date,
            job_count,
            unique_companies
        FROM gold.demand_by_role
        WHERE canonical_role = ?
        ORDER BY date DESC
        LIMIT 30
        """,
        [role],
    ).df()
    return df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# Tool 4 — salary trends
# ---------------------------------------------------------------------------

def get_salary_trends(role: str, city: Optional[str] = None) -> list[dict]:
    """
    Return salary statistics (USD) for a role, optionally filtered by city.

    Columns: city, jobs_with_salary, min_salary_usd, avg_min_salary_usd,
             avg_max_salary_usd, max_salary_usd, median_min_usd.
    """
    conn = get_pipeline().conn

    if city:
        df = conn.execute(
            """
            SELECT
                city,
                jobs_with_salary,
                min_salary_usd,
                avg_min_salary_usd,
                avg_max_salary_usd,
                max_salary_usd,
                median_min_usd
            FROM gold.salary_trends
            WHERE canonical_role = ?
              AND city = ?
            ORDER BY jobs_with_salary DESC
            """,
            [role, city],
        ).df()
    else:
        df = conn.execute(
            """
            SELECT
                city,
                jobs_with_salary,
                min_salary_usd,
                avg_min_salary_usd,
                avg_max_salary_usd,
                max_salary_usd,
                median_min_usd
            FROM gold.salary_trends
            WHERE canonical_role = ?
            ORDER BY jobs_with_salary DESC
            """,
            [role],
        ).df()

    return df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# Tool 5 — compare skills (CV gap analysis)
# ---------------------------------------------------------------------------

def compare_skills(cv_skills: list[str], role: str) -> dict:
    """
    Compare a CV skill list against the top demanded skills for a role.

    Returns:
        skills_you_have      skills present in both CV and top market demand
        skills_missing       top demanded skills absent from the CV
        additional_skills    CV skills not in the top-20 demand list
        market_coverage_pct  % of top-20 demanded skills covered by the CV
    """
    demanded = get_top_skills(role, limit=20)

    if not demanded:
        return {
            "skills_you_have": [],
            "skills_missing": [],
            "additional_skills": sorted(s.lower() for s in cv_skills),
            "market_coverage_pct": 0.0,
        }

    demanded_set = {s["skill"].lower() for s in demanded}
    cv_set = {s.lower() for s in cv_skills}

    coverage = round(
        100 * len(cv_set & demanded_set) / len(demanded_set), 1
    )

    return {
        "skills_you_have": sorted(cv_set & demanded_set),
        "skills_missing": sorted(demanded_set - cv_set),
        "additional_skills": sorted(cv_set - demanded_set),
        "market_coverage_pct": coverage,
    }
