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


@mcp.tool()
def search_and_scrape_role(role: str) -> str:
    """
    Search for jobs for a specific role or search query on GetOnBoard in real-time,
    scrape them, run them through the Medallion pipeline (Bronze -> Silver -> Gold),
    and display the results.

    Use this tool when a user searches for a role that is either new or has
    outdated data to immediately ingest and view the latest jobs.

    Args:
        role: The role name or search query (e.g. 'devops', 'kubernetes', 'data engineer').
    """
    import sys
    import logging
    from datetime import datetime, timezone
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Lazy imports of heavy scraper packages to keep start-up times fast
    from scraper.client import GetOnBoardClient
    from scraper.checkpoint import ScrapingCheckpoint
    from scraper.parser import parse_jobs, parse_job_details
    from scraper.exporter import export_jobs, DatasetLineage
    from scraper.quality import DataQualityValidator
    from scraper.config import settings
    from scraper.medallion import MedallionPipeline
    from role_mapper.role_mapper import RoleMapper

    logger = logging.getLogger("mcp_server.search_and_scrape")

    # 1. Resolve canonical role key
    logger.warning(f"Resolving canonical role for term: '{role}'...")
    role_yaml = str(queries._PROJECT_ROOT / "role_mapper" / "config" / "roles.yaml")
    role_mapper = RoleMapper(role_yaml, google_api_key=settings.google_api_key)
    canonical = role_mapper.find_role(role)

    search_terms = [role]
    if canonical:
        role_key = canonical.role_key
    else:
        # Unknown role: generate with Gemini or fallback templates to get a canonical key
        gen_data = role_mapper.generate_variants_with_gemini(role)
        role_key = gen_data["role_key"] if gen_data else role.lower().replace(" ", "_")

    # 2. Reset read-only pipeline connection to allow write access to DuckDB
    queries.reset_pipeline()

    client = None
    checkpoint = None
    pipeline = None
    all_jobs = []

    try:
        client = GetOnBoardClient()
        checkpoint = ScrapingCheckpoint()
        validator = DataQualityValidator()

        # Scrape each term (limited to max 2 search terms for speed)
        for term in search_terms:
            logger.warning(f"Scraping term '{term}' on GetOnBoard...")
            html = client.search(term)
            jobs = parse_jobs(html, term)

            logger.warning(f"Found {len(jobs)} jobs on the search page.")

            # Filter already processed URLs
            unprocessed_urls = checkpoint.get_unprocessed_urls([job.url for job in jobs])
            # Limit to at most 10 new jobs per search term to keep real-time response fast
            unique_jobs = [j for j in jobs if j.url in unprocessed_urls][:10]
            skipped = len(jobs) - len(unique_jobs)

            if not unique_jobs:
                logger.warning(f"All {len(jobs)} jobs for '{term}' are already processed or skipped.")
                continue

            logger.warning(f"Fetching details for {len(unique_jobs)} new jobs concurrently...")
            def fetch_job_html(j):
                try:
                    html_content = client.get_job_details(j.url)
                    return j, html_content, None
                except Exception as err:
                    return j, None, err

            job_htmls = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(fetch_job_html, job): job for job in unique_jobs}
                for future in as_completed(futures):
                    job_htmls.append(future.result())

            for idx, (job, html_content, err) in enumerate(job_htmls, 1):
                try:
                    if err:
                        raise err

                    details = parse_job_details(html_content)
                    job.description = details.get("description")
                    job.description_extraction_method = details.get("description_extraction_method")
                    job.description_confidence = details.get("description_confidence")
                    job.skills = details.get("skills")
                    job.skills_confidence = details.get("skills_confidence")
                    job.experience_level = details.get("experience_level")
                    job.contract_type = details.get("contract_type")
                    job.job_category = details.get("job_category")
                    job.processing_timestamp = datetime.now(timezone.utc)

                    is_valid, errors = validator.validate_record(job.model_dump())
                    job.is_valid = is_valid
                    job.validation_errors = errors if errors else None

                    checkpoint.mark_processed(
                        url=job.url,
                        search_term=term,
                        role=role_key,
                        confidence_score=job.description_confidence,
                        extraction_method=job.description_extraction_method
                    )
                    all_jobs.append(job)
                except Exception as ex:
                    logger.warning(f"Failed to process job details for {job.url}: {ex}")
                    checkpoint.mark_failed(
                        url=job.url,
                        search_term=term,
                        role=role_key,
                        error_message=str(ex)
                    )

        # 3. Export to Bronze and run Medallion pipeline if new jobs were ingested
        if all_jobs:
            logger.warning(f"Exporting {len(all_jobs)} jobs to Bronze...")
            quality_report = validator.validate_batch([j.model_dump() for j in all_jobs])
            lineage = DatasetLineage(
                source_url="https://www.getonbrd.com/jobs",
                source_type="web_scrape",
                extraction_method="getonboard_scraper_v2",
                extraction_timestamp=datetime.now(timezone.utc).isoformat(),
                record_count=len(all_jobs),
                schema_version="JobV2",
                data_quality_metrics=quality_report.metrics.__dict__,
                owner="data-engineering@company.com"
            )
            safe_role_key = "".join([c if c.isalnum() else "_" for c in role_key]).lower()
            output_file = export_jobs(all_jobs, role=safe_role_key, lineage=lineage)
            logger.warning(f"Bronze layer written: {output_file}")

            logger.warning("Running Medallion pipeline (Bronze -> Silver -> Gold)...")
            pipeline = MedallionPipeline()
            pipeline.run_full_pipeline()
            pipeline.close()

            # Retrieve updated stats from Gold tables
            temp_pipeline = MedallionPipeline(read_only=True)
            try:
                demand_df = temp_pipeline.query(
                    "SELECT date, job_count, unique_companies FROM gold.demand_by_role WHERE canonical_role = ? ORDER BY date DESC LIMIT 1",
                    [role_key]
                )
                skills_df = temp_pipeline.query(
                    "SELECT skill, mention_count, pct_of_role_jobs FROM gold.skills_frequency WHERE canonical_role = ? ORDER BY mention_count DESC LIMIT 5",
                    [role_key]
                )

                demand_info = demand_df.to_dict(orient="records")
                skills_info = skills_df.to_dict(orient="records")
            finally:
                temp_pipeline.close()

            # Format the output as Markdown
            md_output = [
                f"### 🚀 Scraping & Ingestion Complete for Role: **{role}** (Key: `{role_key}`)",
                f"- **New jobs scraped and ingested:** {len(all_jobs)}",
                f"- **Search terms processed:** {', '.join(search_terms)}",
                f"- **Data Quality:** {quality_report.metrics.valid_records} valid, {quality_report.metrics.invalid_records} invalid (Avg confidence: {round(quality_report.metrics.avg_confidence, 2) if quality_report.metrics.avg_confidence else 'N/A'})",
                "\n#### 📊 Market Summary (Gold Layer):"
            ]

            if demand_info:
                md_output.append(f"- **Latest active job count ({demand_info[0]['date']}):** {demand_info[0]['job_count']} jobs from {demand_info[0]['unique_companies']} unique companies.")

            if skills_info:
                md_output.append("\n#### 🛠️ Top 5 Demanded Skills:")
                for s in skills_info:
                    md_output.append(f"1. **{s['skill']}**: {s['mention_count']} mentions ({round(s['pct_of_role_jobs'] * 100, 1)}% of jobs)")
            else:
                md_output.append("\n*(Not enough skills data yet)*")

            return "\n".join(md_output)

        else:
            return (
                f"### 🔍 Search for Role: **{role}** (Key: `{role_key}`)\n"
                f"- **Status:** No new job postings were found on GetOnBoard during this execution.\n"
                f"- **Search terms verified:** {', '.join(search_terms)}\n"
                f"- **Note:** All available listings are already processed or no new listings exist."
            )

    except Exception as e:
        logger.error(f"Error scraping role: {e}", exc_info=True)
        return f"### ❌ Error during scraping of **{role}**\n- **Error detail:** {str(e)}"

    finally:
        # Clean up local references
        if client:
            client.close()
        if checkpoint:
            checkpoint.close()
        if pipeline:
            pipeline.close()
        # Restore read-only singleton connection
        queries.get_pipeline(read_only=True)
