"""
MCP Server — Job Market Pipeline

Exposes the Gold layer of the pipeline to Claude via the Model Context Protocol.
Uses stdio transport by default (compatible with Claude Desktop and MCP Inspector).

Tools:
    get_available_roles  — list roles with job counts
    get_top_skills       — most demanded skills for a role
    get_demand_trends    — daily job counts (last 30 days)
    get_salary_trends    — salary min/avg/max/median by city
    compare_skills       — CV gap analysis vs market demand

Usage:
    python run_mcp.py                     # start the server (stdio)
    npx @modelcontextprotocol/inspector python run_mcp.py  # web inspector
"""

from mcp.server.fastmcp import FastMCP

from mcp_server import queries

mcp = FastMCP("job-market-pipeline")

# Open the DB in read-only mode at startup.
# This releases the exclusive file lock so the scraper can write to
# pipeline.duckdb concurrently while the MCP server is running.
queries.get_pipeline(read_only=True)


@mcp.tool()
def get_available_roles() -> list[dict]:
    """List all canonical roles present in the database with their total job count."""
    return queries.get_available_roles()


@mcp.tool()
def get_top_skills(role: str, limit: int = 20) -> list[dict]:
    """
    Return the most demanded skills for a role.

    Args:
        role:  Canonical role key, e.g. 'data_engineer', 'data_analyst'.
               Call get_available_roles() first to see what roles exist.
        limit: Number of top skills to return (default 20, max 50).

    Returns list of {skill, mention_count, pct} sorted by mention_count desc.
    """
    return queries.get_top_skills(role, limit)


@mcp.tool()
def get_demand_trends(role: str) -> list[dict]:
    """
    Return daily job demand trends for a role over the last 30 days.

    Args:
        role: Canonical role key (e.g. 'data_engineer').

    Returns list of {date, job_count, unique_companies} ordered by date desc.
    """
    return queries.get_demand_trends(role)


@mcp.tool()
def get_salary_trends(role: str, city: str | None = None) -> list[dict]:
    """
    Return salary statistics (USD) for a role, optionally filtered by city.

    Args:
        role: Canonical role key (e.g. 'data_engineer').
        city: Optional city name to narrow results (e.g. 'Santiago').
              Pass None to see all cities for the role.

    Returns list of {city, jobs_with_salary, min_salary_usd,
    avg_min_salary_usd, avg_max_salary_usd, max_salary_usd, median_min_usd}.
    """
    return queries.get_salary_trends(role, city)


@mcp.tool()
def compare_skills(cv_skills: list[str], role: str) -> dict:
    """
    Compare a list of skills extracted from a CV against market demand for a role.

    Use this after extracting skills from a pasted CV to produce a gap analysis.

    Args:
        cv_skills: List of skill strings extracted from the CV.
                   Example: ["Python", "SQL", "Spark", "dbt", "Kafka"]
        role:      Canonical role key to compare against (e.g. 'data_engineer').

    Returns:
        skills_you_have      Skills present in both the CV and top-20 market demand.
        skills_missing       Top demanded skills absent from the CV (priority gaps).
        additional_skills    CV skills not in the top-20 list (still valuable).
        market_coverage_pct  Percentage of top-20 demanded skills covered by the CV.
    """
    return queries.compare_skills(cv_skills, role)
