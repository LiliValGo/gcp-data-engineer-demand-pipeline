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
  - Silver is compatible with BigQuery SQL (same DuckDB dialect).
  - Gold tables are exposed to Claude via the MCP Server.
"""

import re
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timezone

import duckdb
import pandas as pd
import httpx

from role_mapper.role_mapper import RoleMapper

logger = logging.getLogger(__name__)

# Exchange rates fallback to USD (approximate, May 2026)
_FX_FALLBACK = {
    "USD": 1.0,
    "CLP": 0.00106,  # Chilean Peso (~945 CLP/USD)
    "ARS": 0.001,    # Argentine Peso (~1000 ARS/USD, official rate)
    "MXN": 0.056,    # Mexican Peso (~17.9 MXN/USD)
    "COP": 0.000244, # Colombian Peso (~4100 COP/USD)
    "BRL": 0.178,    # Brazilian Real (~5.6 BRL/USD)
    "PEN": 0.267,    # Peruvian Sol (~3.74 PEN/USD)
}


def _fetch_fx_rates() -> dict:
    """Fetch latest exchange rates to USD from frankfurter.app API with fallback."""
    try:
        response = httpx.get(
            "https://api.frankfurter.app/latest?from=USD&to=CLP,ARS,MXN,COP,BRL,PEN",
            timeout=5.0
        )
        if response.status_code == 200:
            data = response.json()
            rates = data.get("rates", {})
            fx_to_usd = {"USD": 1.0}
            for currency, rate in rates.items():
                if rate > 0:
                    fx_to_usd[currency] = round(1.0 / rate, 6)
            
            # Keep fallback for anything missing
            for curr, val in _FX_FALLBACK.items():
                if curr not in fx_to_usd:
                    fx_to_usd[curr] = val
                    
            logger.info(f"Successfully fetched live exchange rates: {fx_to_usd}")
            return fx_to_usd
    except Exception as e:
        logger.warning(f"Failed to fetch live FX rates, using local fallback: {e}")
        
    return _FX_FALLBACK

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
        from .config import settings
        self.is_gcs = False
        if settings.gcs_bucket:
            self.bronze_root_str = f"gs://{settings.gcs_bucket}/bronze"
            self.is_gcs = True
        elif str(bronze_root).startswith("gs://"):
            self.bronze_root_str = str(bronze_root)
            self.is_gcs = True
        else:
            self.bronze_root_str = str(bronze_root)

        self.duckdb_path = Path(duckdb_path)
        self.bronze_root = Path(bronze_root)
        if not self.is_gcs and not read_only:
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

        self.fx_rates = _fetch_fx_rates()

        logger.info(f"MedallionPipeline initialized — warehouse: {self.duckdb_path} (is_gcs: {self.is_gcs})")

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

        # Indexes for common filter queries
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_silver_search_term ON silver.jobs(search_term)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_silver_canonical_role ON silver.jobs(canonical_role)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_silver_url ON silver.jobs(url)")

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
            fx = self.fx_rates.get(currency, 1.0)
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
        if self.is_gcs:
            import gcsfs
            fs = gcsfs.GCSFileSystem()
            path_str = self.bronze_root_str.replace("gs://", "")
            all_files = fs.glob(f"{path_str}/**/*.parquet")
            parquet_files = [f"gs://{f}" for f in all_files]
        else:
            parquet_files = list(self.bronze_root.rglob("*.parquet"))

        if not parquet_files:
            logger.warning(f"No Bronze parquet files found in {self.bronze_root_str}")
            return 0

        # --- Incremental load: skip files already ingested into Silver ---
        # Avoids reloading all historical Parquet files on every pipeline run.
        try:
            if self.is_gcs:
                from google.cloud import bigquery
                from scraper.config import settings
                bq_client = bigquery.Client()
                query = f"SELECT DISTINCT bronze_file_path FROM `{settings.gcp_project}.silver.jobs` WHERE bronze_file_path IS NOT NULL"
                query_job = bq_client.query(query)
                processed_paths = set(row.bronze_file_path for row in query_job.result())
            else:
                processed_paths = set(
                    self.conn.execute(
                        "SELECT DISTINCT bronze_file_path FROM silver.jobs WHERE bronze_file_path IS NOT NULL"
                    ).fetchdf()["bronze_file_path"].tolist()
                )
        except Exception:
            processed_paths = set()

        new_files = [fp for fp in parquet_files if str(fp) not in processed_paths]

        if not new_files:
            if self.is_gcs:
                from google.cloud import bigquery
                from scraper.config import settings
                bq_client = bigquery.Client()
                try:
                    query = f"SELECT COUNT(*) as count FROM `{settings.gcp_project}.silver.jobs`"
                    count = list(bq_client.query(query).result())[0].count
                except Exception:
                    count = 0
            else:
                count = self.conn.execute("SELECT COUNT(*) FROM silver.jobs").fetchone()[0]
            logger.info(f"No new Bronze files to process — Silver already up to date ({count} rows)")
            return count

        logger.info(f"Loading {len(new_files)} new Bronze file(s) (skipping {len(parquet_files) - len(new_files)} already in Silver)...")

        # --- Step 1: Load only new Bronze files into a single DataFrame ---
        frames = []
        for fp in new_files:
            df = pd.read_parquet(fp)
            df["_bronze_file_path"] = str(fp)
            frames.append(df)

        raw_df = pd.concat(frames, ignore_index=True)
        logger.info(f"Bronze: {len(raw_df)} total rows before deduplication")

        # --- Step 2: Apply Python transformations via apply/vectorized operations ---
        raw_df = raw_df[raw_df["url"].fillna("").str.strip() != ""].copy()
        if raw_df.empty:
            logger.warning("No valid records after filtering empty URLs")
            return 0

        raw_df["job_id"] = raw_df["url"].apply(self._make_job_id)
        
        parsed_salaries = raw_df["salary"].apply(self._parse_salary)
        raw_df["salary_usd_min"] = parsed_salaries.apply(lambda x: x[0])
        raw_df["salary_usd_max"] = parsed_salaries.apply(lambda x: x[1])

        parsed_locations = raw_df["location"].apply(self._parse_location)
        raw_df["city"] = parsed_locations.apply(lambda x: x[0])
        raw_df["is_remote"] = parsed_locations.apply(lambda x: x[1])

        raw_df["canonical_role"] = raw_df["search_term"].apply(self._get_canonical_role)
        raw_df["salary_raw"] = raw_df["salary"]
        raw_df["processing_timestamp"] = datetime.now(timezone.utc).isoformat()
        
        # Ensure all required columns exist in raw_df, fill with None if missing
        required_cols = [
            "job_id", "url", "title", "company", "canonical_role", "search_term",
            "location", "city", "is_remote", "salary_raw", "salary_usd_min",
            "salary_usd_max", "description", "skills", "experience_level",
            "contract_type", "job_category", "extraction_quality_score",
            "scraped_at", "processing_timestamp", "bronze_file_path"
        ]
        
        if "_bronze_file_path" in raw_df.columns:
            raw_df = raw_df.rename(columns={"_bronze_file_path": "bronze_file_path"})
            
        for col in required_cols:
            if col not in raw_df.columns:
                raw_df[col] = None

        silver_df = raw_df[required_cols].copy()

        # --- Step 3: Deduplicate — keep latest scraped_at per URL ---
        # This mirrors the BigQuery pattern:
        #   ROW_NUMBER() OVER (PARTITION BY url ORDER BY scraped_at DESC) = 1
        silver_df["_rn"] = (
            silver_df.sort_values("scraped_at", ascending=False)
            .groupby("url")
            .cumcount()
        )
        silver_df = silver_df[silver_df["_rn"] == 0].drop(columns=["_rn"])

        # --- Step 4: Upsert into DuckDB or BigQuery silver.jobs ---
        if self.is_gcs:
            from google.cloud import bigquery
            from scraper.config import settings
            bq_client = bigquery.Client()
            
            dataset_ref = bigquery.DatasetReference(settings.gcp_project, "silver")
            bq_client.create_dataset(dataset_ref, exists_ok=True)
            
            staging_table_id = f"{settings.gcp_project}.silver.jobs_staging"
            dest_table_id = f"{settings.gcp_project}.silver.jobs"
            
            job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
            job = bq_client.load_table_from_dataframe(silver_df, staging_table_id, job_config=job_config)
            job.result()
            
            try:
                bq_client.get_table(dest_table_id)
                dml = f"""
                    BEGIN TRANSACTION;
                    DELETE FROM `{dest_table_id}` WHERE job_id IN (SELECT job_id FROM `{staging_table_id}`);
                    INSERT INTO `{dest_table_id}` SELECT * FROM `{staging_table_id}`;
                    DROP TABLE `{staging_table_id}`;
                    COMMIT TRANSACTION;
                """
                bq_client.query(dml).result()
            except Exception:
                job_config = bigquery.LoadJobConfig(write_disposition="WRITE_EMPTY")
                bq_client.load_table_from_dataframe(silver_df, dest_table_id, job_config=job_config).result()
                bq_client.delete_table(staging_table_id, not_found_ok=True)
                
            query = f"SELECT COUNT(*) as count FROM `{dest_table_id}`"
            count = list(bq_client.query(query).result())[0].count
            logger.info(f"Silver (BigQuery): {count} total rows in silver.jobs after upsert")
            return count
        else:
            self.conn.register("_silver_staging", silver_df)

            self.conn.execute("""
                DELETE FROM silver.jobs WHERE job_id IN (SELECT job_id FROM _silver_staging);

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
        each run. This is appropriate for small datasets (<1M rows).
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
        # Answers: "What % of jobs for this role mention each skill?"
        # UNNEST expands the VARCHAR[] array into individual rows.
        # pct_of_role_jobs = jobs mentioning the skill / total jobs with skills for that role.
        # (Previous formula used total skill mentions as denominator, which was misleading.)
        self.conn.execute("""
            CREATE OR REPLACE TABLE gold.skills_frequency AS
            WITH skills_unnested AS (
                SELECT
                    job_id,
                    canonical_role,
                    LOWER(TRIM(skill)) AS skill
                FROM silver.jobs,
                    LATERAL UNNEST(skills) AS t(skill)
                WHERE skills IS NOT NULL
            ),
            role_job_counts AS (
                SELECT
                    canonical_role,
                    COUNT(DISTINCT job_id) AS total_jobs_with_skills
                FROM silver.jobs
                WHERE skills IS NOT NULL
                GROUP BY canonical_role
            )
            SELECT
                su.canonical_role,
                su.skill,
                COUNT(*)                                               AS mention_count,
                ROUND(
                    COUNT(DISTINCT su.job_id) * 100.0 / rjc.total_jobs_with_skills,
                    2
                )                                                      AS pct_of_role_jobs
            FROM skills_unnested su
            JOIN role_job_counts rjc USING (canonical_role)
            GROUP BY su.canonical_role, su.skill, rjc.total_jobs_with_skills
            ORDER BY su.canonical_role, mention_count DESC
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
        start = datetime.now(timezone.utc)

        silver_rows = self.run_bronze_to_silver()
        if silver_rows > 0:
            if self.is_gcs:
                logger.info("Running dbt on BigQuery for Gold layer...")
                import subprocess
                try:
                    res = subprocess.run(
                        ["dbt", "run", "--target", "prod"],
                        cwd="transform",
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    logger.info(f"dbt run succeeded:\n{res.stdout}")
                except subprocess.CalledProcessError as e:
                    logger.error(f"dbt run failed:\n{e.stderr}\n{e.stdout}")
                    raise
            else:
                self.run_silver_to_gold()

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(f"=== Medallion Pipeline finished in {elapsed:.1f}s ===")

    # ------------------------------------------------------------------
    # Introspection helpers (used by tests and the MCP server)
    # ------------------------------------------------------------------

    def query(self, sql: str, params: list = None) -> pd.DataFrame:
        """
        Execute a SQL query and return a pandas DataFrame.
        Works for both DuckDB locally and BigQuery in production.
        """
        if self.is_gcs:
            from google.cloud.bigquery import dbapi
            # Use BigQuery DB-API connection
            conn = dbapi.connect()
            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            # Fetch results into DataFrame
            columns = [col[0] for col in cursor.description] if cursor.description else []
            data = cursor.fetchall()
            return pd.DataFrame(data, columns=columns)
        else:
            if params:
                return self.conn.execute(sql, params).df()
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
