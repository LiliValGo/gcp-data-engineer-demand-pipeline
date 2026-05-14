"""
Medallion Architecture Pipeline: Bronze → Silver → Gold

This module implements the three-layer data architecture that is the industry
standard for data lakes and warehouse platforms (Databricks, BigQuery, Snowflake).

Layers:
  Bronze — Raw data exactly as scraped. Immutable. No transformations.
  Silver — Cleaned, normalized, deduplicated. Source of truth for analysis.
  Gold   — Aggregated analytics. Optimized for queries and dashboards.

Why this matters:
  - If a transformation has a bug, you can always replay from Bronze.
  - Silver is 90% compatible with BigQuery SQL (same DuckDB dialect).
  - Gold tables are exposed to Claude via the MCP Server (Phase 2, complete).
"""

import re
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

import duckdb
import pandas as pd

from role_mapper.role_mapper import RoleMapper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exchange rates to USD (approximate, hardcoded for Phase 1 — Phase 4
# will fetch live rates from a GCP Secret Manager-stored FX API key)
# ---------------------------------------------------------------------------
_FX_TO_USD = {
    "USD": 1.0,
    "CLP": 0.0011,  # Chilean Peso
    "ARS": 0.0012,  # Argentine Peso (highly volatile)
    "MXN": 0.058,   # Mexican Peso
    "COP": 0.00025, # Colombian Peso
    "BRL": 0.20,    # Brazilian Real
    "PEN": 0.27,    # Peruvian Sol
}

# Salary pattern: captures optional currency, numbers (with . or , separators)
# Examples matched: "USD 100,000", "USD 3.500", "ARS 80.000 - 120.000", "200"
_SALARY_RE = re.compile(
    r"(?P<currency>USD|CLP|ARS|MXN|COP|BRL|PEN)?\s*"
    r"(?P<min>[\d][,.\d]*)"
    r"(?:\s*[-–]\s*(?P<max>[\d][,.\d]*))?"
    r"(?:\s*(?P<period>mes|month|year|año|annual))?",
    re.IGNORECASE,
)

# Remote keywords to normalize location
_REMOTE_KEYWORDS = {"remote", "remoto", "full remote", "100% remote", "100% remoto"}


class MedallionPipeline:
    """
    Orchestrates the Bronze → Silver → Gold data transformation pipeline.

    Uses a single DuckDB file as the local data warehouse, which mirrors
    the BigQuery dataset-per-layer model used in production.

    Usage:
        pipeline = MedallionPipeline()
        pipeline.run_full_pipeline()
        pipeline.close()

    Or as a context manager:
        with MedallionPipeline() as pipeline:
            pipeline.run_full_pipeline()
    """

    def __init__(
        self,
        duckdb_path: str = "data/pipeline.duckdb",
        bronze_root: str = "data/bronze",
        role_mapper_config: str = "role_mapper/config/roles.yaml",
        read_only: bool = False,
    ):
        self.duckdb_path = Path(duckdb_path)
        self.bronze_root = Path(bronze_root)
        if not read_only:
            self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = duckdb.connect(str(self.duckdb_path), read_only=read_only)
        if not read_only:
            self._init_schemas()

        # RoleMapper is used to normalize each job's search_term to a
        # canonical role_key (e.g. "ingeniero de datos" → "data_engineer")
        try:
            self._role_mapper = RoleMapper(role_mapper_config)
        except Exception as e:
            logger.warning(f"RoleMapper not available: {e} — canonical_role will use search_term as fallback")
            self._role_mapper = None

        logger.info(f"MedallionPipeline initialized — warehouse: {self.duckdb_path}")

    # ------------------------------------------------------------------
    # Internal: Schema + Table setup
    # ------------------------------------------------------------------

    def _init_schemas(self) -> None:
        """Create silver and gold schemas and their tables if they don't exist."""
        self.conn.execute("CREATE SCHEMA IF NOT EXISTS silver")
        self.conn.execute("CREATE SCHEMA IF NOT EXISTS gold")

        # Silver: one canonical job per URL (latest scrape wins on replay)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS silver.jobs (
                job_id        VARCHAR PRIMARY KEY,
                url           VARCHAR,
                title         VARCHAR,
                company       VARCHAR,
                canonical_role VARCHAR,
                search_term    VARCHAR,
                location       VARCHAR,
                city           VARCHAR,
                is_remote      BOOLEAN,
                salary_raw     VARCHAR,
                salary_usd_min DOUBLE,
                salary_usd_max DOUBLE,
                description    VARCHAR,
                skills         VARCHAR[],
                experience_level VARCHAR,
                contract_type    VARCHAR,
                job_category     VARCHAR,
                extraction_quality_score DOUBLE,
                scraped_at           TIMESTAMP,
                processing_timestamp TIMESTAMP,
                bronze_file_path     VARCHAR
            )
        """)

        # Gold tables are created by run_silver_to_gold() using CREATE OR REPLACE,
        # so no DDL needed here.
        logger.debug("Schemas initialized")

    # ------------------------------------------------------------------
    # Internal: Transformation helpers
    # (Python functions — easier to test than SQL UDFs for complex logic)
    # ------------------------------------------------------------------

    def _parse_salary(
        self, salary_raw: Optional[str]
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Parse a free-text salary string into (min_usd, max_usd).

        Examples:
            "USD 100,000 - 140,000" → (100000.0, 140000.0)
            "ARS 80.000 - 120.000"  → (96.0, 144.0)   after FX
            "USD 3,500 /mes"        → (42000.0, None)   monthly × 12
            None                    → (None, None)
        """
        if not salary_raw:
            return None, None

        match = _SALARY_RE.search(salary_raw.replace(",", "").replace(".", "").replace(" ", ""))
        if not match:
            # Retry with original string (some salaries use "." as thousands sep)
            match = _SALARY_RE.search(salary_raw)
        if not match:
            return None, None

        try:
            currency = (match.group("currency") or "USD").upper()
            fx = _FX_TO_USD.get(currency, 1.0)
            period = (match.group("period") or "").lower()

            # Clean number: remove all non-digit characters
            raw_min = re.sub(r"[^\d]", "", match.group("min") or "")
            raw_max = re.sub(r"[^\d]", "", match.group("max") or "") if match.group("max") else None

            if not raw_min:
                return None, None

            sal_min = float(raw_min) * fx
            sal_max = float(raw_max) * fx if raw_max else None

            # Monthly → annual conversion
            if period in ("mes", "month"):
                sal_min *= 12
                sal_max = sal_max * 12 if sal_max else None

            # Sanity check: if salary is suspiciously large (e.g. raw CLP value
            # after bad FX), cap and log
            if sal_min > 1_000_000:
                logger.debug(f"Salary out of range, skipping: {salary_raw!r}")
                return None, None

            return round(sal_min, 2), round(sal_max, 2) if sal_max else None

        except (ValueError, AttributeError) as e:
            logger.debug(f"Salary parse failed for {salary_raw!r}: {e}")
            return None, None

    def _parse_location(self, location_raw: Optional[str]) -> Tuple[Optional[str], bool]:
        """
        Parse a location string into (city, is_remote).

        Examples:
            "Remote"              → (None, True)
            "Santiago, Chile"     → ("Santiago", False)
            "Hybrid - Buenos Aires" → ("Buenos Aires", False)
        """
        if not location_raw:
            return None, False

        # Take only the first line — GetonBoard appends descriptive text
        # after newlines (e.g. "Santiago\n\nThis job is performed partly...")
        cleaned = location_raw.strip().split("\n")[0].strip()

        # Check for remote first
        if cleaned.lower() in _REMOTE_KEYWORDS:
            return None, True
        if "remote" in cleaned.lower() and "hybrid" not in cleaned.lower():
            return None, True

        # Extract city from patterns like "City, Country" or "Hybrid - City"
        city = re.sub(r"(?i)hybrid\s*[-–]\s*", "", cleaned)  # remove "Hybrid - "
        city = city.split(",")[0].strip()                     # take first part before comma
        city = city.strip() if city else None

        return city or None, False

    def _get_canonical_role(self, search_term: Optional[str]) -> str:
        """
        Map a search term to a canonical role key via RoleMapper.

        Falls back to a cleaned version of the search_term if no mapper
        or no match is found.
        """
        if not search_term:
            return "unknown"

        if self._role_mapper:
            role = self._role_mapper.find_role(search_term)
            if role:
                return role.role_key

        # Fallback: slugify the search term
        return re.sub(r"[^a-z0-9]+", "_", search_term.lower()).strip("_")

    @staticmethod
    def _make_job_id(url: str) -> str:
        """
        Generate a stable, deterministic job ID from a URL.

        MD5 is sufficient here — we are not using this for security,
        just as a stable deduplication key that mirrors BigQuery's
        GENERATE_UUID() / FARM_FINGERPRINT() patterns.
        """
        return hashlib.md5(url.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Bronze → Silver
    # ------------------------------------------------------------------

    def run_bronze_to_silver(self) -> int:
        """
        Read all Bronze Parquet files, apply transformations, and upsert
        into silver.jobs.

        Returns:
            Number of rows written to silver.jobs in this run.

        Why upsert and not overwrite?
        If the scraper runs twice in one day, we want Silver to reflect
        the latest data per URL without duplicating records. ON CONFLICT
        (url deduplication) ensures idempotency.
        """
        parquet_pattern = str(self.bronze_root / "**" / "*.parquet")
        parquet_files = list(self.bronze_root.rglob("*.parquet"))

        if not parquet_files:
            logger.warning(f"No Bronze parquet files found in {self.bronze_root}")
            return 0

        logger.info(f"Loading {len(parquet_files)} Bronze file(s)...")

        # --- Step 1: Load all Bronze files into a single DataFrame ---
        frames = []
        for fp in parquet_files:
            df = pd.read_parquet(fp)
            df["_bronze_file_path"] = str(fp)
            frames.append(df)

        raw_df = pd.concat(frames, ignore_index=True)
        logger.info(f"Bronze: {len(raw_df)} total rows before deduplication")

        # --- Step 2: Apply Python transformations row-by-row ---
        records = []
        for _, row in raw_df.iterrows():
            url = str(row.get("url", "")) or ""
            if not url:
                continue

            sal_min, sal_max = self._parse_salary(row.get("salary"))
            city, is_remote = self._parse_location(row.get("location"))
            canonical_role = self._get_canonical_role(row.get("search_term"))

            records.append({
                "job_id":        self._make_job_id(url),
                "url":           url,
                "title":         row.get("title"),
                "company":       row.get("company"),
                "canonical_role": canonical_role,
                "search_term":   row.get("search_term"),
                "location":      row.get("location"),
                "city":          city,
                "is_remote":     is_remote,
                "salary_raw":    row.get("salary"),
                "salary_usd_min": sal_min,
                "salary_usd_max": sal_max,
                "description":   row.get("description"),
                "skills":        row.get("skills"),
                "experience_level": row.get("experience_level"),
                "contract_type": row.get("contract_type"),
                "job_category":  row.get("job_category"),
                "extraction_quality_score": row.get("extraction_quality_score"),
                "scraped_at":    row.get("scraped_at"),
                "processing_timestamp": datetime.utcnow().isoformat(),
                "bronze_file_path": row.get("_bronze_file_path"),
            })

        if not records:
            logger.warning("No valid records after transformation")
            return 0

        silver_df = pd.DataFrame(records)

        # --- Step 3: Deduplicate — keep latest scraped_at per URL ---
        # This mirrors the BigQuery pattern:
        #   ROW_NUMBER() OVER (PARTITION BY url ORDER BY scraped_at DESC) = 1
        silver_df["_rn"] = (
            silver_df.sort_values("scraped_at", ascending=False)
            .groupby("url")
            .cumcount()
        )
        silver_df = silver_df[silver_df["_rn"] == 0].drop(columns=["_rn"])

        # --- Step 4: Upsert into DuckDB silver.jobs ---
        # Register the DataFrame as a temporary DuckDB view, then INSERT
        # with ON CONFLICT. This is the DuckDB equivalent of BigQuery's MERGE.
        self.conn.register("_silver_staging", silver_df)

        self.conn.execute("""
            INSERT INTO silver.jobs
            SELECT
                job_id, url, title, company, canonical_role, search_term,
                location, city, is_remote, salary_raw, salary_usd_min,
                salary_usd_max, description, skills, experience_level,
                contract_type, job_category, extraction_quality_score,
                TRY_CAST(scraped_at AS TIMESTAMP),
                TRY_CAST(processing_timestamp AS TIMESTAMP),
                bronze_file_path
            FROM _silver_staging
            ON CONFLICT (job_id) DO UPDATE SET
                title                    = excluded.title,
                company                  = excluded.company,
                canonical_role           = excluded.canonical_role,
                city                     = excluded.city,
                is_remote                = excluded.is_remote,
                salary_usd_min           = excluded.salary_usd_min,
                salary_usd_max           = excluded.salary_usd_max,
                description              = excluded.description,
                skills                   = excluded.skills,
                experience_level         = excluded.experience_level,
                extraction_quality_score = excluded.extraction_quality_score,
                scraped_at               = excluded.scraped_at,
                processing_timestamp     = excluded.processing_timestamp,
                bronze_file_path         = excluded.bronze_file_path
        """)

        self.conn.unregister("_silver_staging")

        count = self.conn.execute("SELECT COUNT(*) FROM silver.jobs").fetchone()[0]
        logger.info(f"Silver: {count} total rows in silver.jobs after upsert")
        return count

    # ------------------------------------------------------------------
    # Silver → Gold
    # ------------------------------------------------------------------

    def run_silver_to_gold(self) -> None:
        """
        Build (or refresh) the three Gold analytics tables from silver.jobs.

        All three tables use CREATE OR REPLACE — they are fully recomputed on
        each run. This is called 'full refresh' and is appropriate for small
        datasets (<1M rows). In Phase 4/BigQuery we will switch to incremental
        writes using MERGE for cost efficiency.
        """
        silver_count = self.conn.execute(
            "SELECT COUNT(*) FROM silver.jobs"
        ).fetchone()[0]

        if silver_count == 0:
            logger.warning("silver.jobs is empty — skipping Gold layer build")
            return

        # --- gold.demand_by_role ---
        # Answers: "How many jobs are posted per role per day?"
        self.conn.execute("""
            CREATE OR REPLACE TABLE gold.demand_by_role AS
            SELECT
                canonical_role,
                CAST(scraped_at AS DATE)      AS date,
                COUNT(*)                       AS job_count,
                COUNT(DISTINCT company)        AS unique_companies,
                AVG(extraction_quality_score)  AS avg_quality_score
            FROM silver.jobs
            GROUP BY canonical_role, CAST(scraped_at AS DATE)
            ORDER BY date DESC, job_count DESC
        """)

        # --- gold.salary_trends ---
        # Answers: "What is the salary range for each role by city?"
        # PERCENTILE_CONT is an ordered-set aggregate — same syntax as BigQuery.
        self.conn.execute("""
            CREATE OR REPLACE TABLE gold.salary_trends AS
            SELECT
                canonical_role,
                COALESCE(city, 'Remote/Unknown')               AS city,
                COUNT(*)                                        AS jobs_with_salary,
                MIN(salary_usd_min)                             AS min_salary_usd,
                AVG(salary_usd_min)                             AS avg_min_salary_usd,
                AVG(salary_usd_max)                             AS avg_max_salary_usd,
                MAX(salary_usd_max)                             AS max_salary_usd,
                PERCENTILE_CONT(0.5) WITHIN GROUP
                    (ORDER BY salary_usd_min)                   AS median_min_usd
            FROM silver.jobs
            WHERE salary_usd_min IS NOT NULL
            GROUP BY canonical_role, COALESCE(city, 'Remote/Unknown')
            ORDER BY canonical_role, jobs_with_salary DESC
        """)

        # --- gold.skills_frequency ---
        # Answers: "What are the most-demanded skills per role?"
        # UNNEST expands the VARCHAR[] array into individual rows.
        # Same syntax works in BigQuery with UNNEST(skills).
        self.conn.execute("""
            CREATE OR REPLACE TABLE gold.skills_frequency AS
            SELECT
                canonical_role,
                LOWER(TRIM(skill))   AS skill,
                COUNT(*)             AS mention_count,
                ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER
                    (PARTITION BY canonical_role), 2) AS pct_of_role_jobs
            FROM silver.jobs,
                LATERAL UNNEST(skills) AS t(skill)
            WHERE skills IS NOT NULL
            GROUP BY canonical_role, LOWER(TRIM(skill))
            ORDER BY canonical_role, mention_count DESC
        """)

        # Log Gold table sizes for observability
        for table in ["demand_by_role", "salary_trends", "skills_frequency"]:
            n = self.conn.execute(f"SELECT COUNT(*) FROM gold.{table}").fetchone()[0]
            logger.info(f"gold.{table}: {n} rows")

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run_full_pipeline(self) -> None:
        """
        Orchestrate the full Bronze → Silver → Gold pipeline.

        This is the single entry point called by main_scraper.py and
        the future CLI command.
        """
        logger.info("=== Medallion Pipeline started ===")
        start = datetime.utcnow()

        silver_rows = self.run_bronze_to_silver()
        if silver_rows > 0:
            self.run_silver_to_gold()

        elapsed = (datetime.utcnow() - start).total_seconds()
        logger.info(f"=== Medallion Pipeline finished in {elapsed:.1f}s ===")

    # ------------------------------------------------------------------
    # Introspection helpers (used by tests and the MCP server)
    # ------------------------------------------------------------------

    def query(self, sql: str) -> pd.DataFrame:
        """
        Execute a SQL query and return a pandas DataFrame.

        Bridge between the local DuckDB warehouse and the MCP Server —
        MCP tools call pipeline.query(sql) and return the result to Claude.
        """
        return self.conn.execute(sql).df()

    def get_gold_summary(self) -> dict:
        """Return row counts for all Gold tables as a health-check dict."""
        tables = ["demand_by_role", "salary_trends", "skills_frequency"]
        summary = {}
        for table in tables:
            try:
                n = self.conn.execute(f"SELECT COUNT(*) FROM gold.{table}").fetchone()[0]
                summary[f"gold.{table}"] = n
            except duckdb.Error:
                summary[f"gold.{table}"] = None
        silver_n = self.conn.execute("SELECT COUNT(*) FROM silver.jobs").fetchone()[0]
        summary["silver.jobs"] = silver_n
        return summary

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self.conn:
            self.conn.close()
            logger.debug("MedallionPipeline connection closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
