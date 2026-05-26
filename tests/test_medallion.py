"""
Tests for scraper/medallion.py

What we test:
- Salary parsing (USD, CLP, ARS, monthly, range)
- Location parsing (remote, city extraction, hybrid)
- Canonical role mapping (via RoleMapper)
- Bronze → Silver transformation (table creation, row count)
- Deduplication (same URL scraped twice → one Silver row)
- Silver → Gold (all three tables populated)
- Empty Bronze handled gracefully (no crash)

Fixtures:
  bronze_parquet — writes a sample parquet file to tmp_path
  pipeline       — MedallionPipeline backed by tmp_path files
"""

import pytest
import pandas as pd
from datetime import datetime
from pathlib import Path

from scraper.medallion import MedallionPipeline


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_sample_jobs(n: int = 3) -> list[dict]:
    """Build a list of minimal job dicts that match the Bronze parquet schema."""
    base = datetime(2026, 3, 28, 10, 0, 0)
    return [
        {
            "title": "Senior Data Engineer",
            "company": "TechCorp",
            "url": f"https://www.getonbrd.com/jobs/de-{i}",
            "search_term": "data engineer",
            "location": "Remote" if i % 2 == 0 else "Santiago, Chile",
            "salary": "USD 100,000 - 140,000" if i % 3 != 2 else "CLP 2.000.000 - 3.000.000",
            "description": "We build large-scale data pipelines using Spark and dbt.",
            "skills": ["Python", "Spark", "SQL"],
            "experience_level": "senior",
            "contract_type": "full-time",
            "job_category": "Data Engineering",
            "is_valid": True,
            "schema_version": 2,
            "extraction_quality_score": 0.88,
            "description_confidence": 0.90,
            "skills_confidence": 0.85,
            "description_extraction_method": "class_search",
            "validation_errors": None,
            "processing_timestamp": base.isoformat(),
            "scraped_at": base.isoformat(),
        }
        for i in range(n)
    ]


@pytest.fixture
def bronze_parquet(tmp_path) -> Path:
    """
    Create a Bronze-style parquet file in tmp_path/bronze/role=data_engineer/.
    Returns the path to the .parquet file.
    """
    bronze_dir = tmp_path / "bronze" / "role=data_engineer"
    bronze_dir.mkdir(parents=True)
    parquet_path = bronze_dir / "2026-03-28T10-00-00__v2.parquet"

    df = pd.DataFrame(_make_sample_jobs(5))
    df.to_parquet(parquet_path, engine="pyarrow", index=False)
    return parquet_path


@pytest.fixture
def pipeline(tmp_path, bronze_parquet) -> MedallionPipeline:
    """
    MedallionPipeline backed by:
      - A temporary DuckDB file
      - The Bronze parquet fixture above

    Cleaned up automatically after each test.
    """
    pl = MedallionPipeline(
        duckdb_path=str(tmp_path / "test_pipeline.duckdb"),
        bronze_root=str(tmp_path / "bronze"),
        role_mapper_config="role_mapper/config/roles.yaml",
    )
    yield pl
    pl.close()


# ---------------------------------------------------------------------------
# Unit tests — Salary parsing
# ---------------------------------------------------------------------------

class TestSalaryParsing:
    """
    Tests for MedallionPipeline._parse_salary()

    Why test this separately?
    Salary parsing is the most complex transformation in Silver. Testing
    it in isolation means a failure here immediately points to the parsing
    logic — not to a problem in the DuckDB layer or parquet loading.
    """

    @pytest.fixture(autouse=True)
    def _pipeline(self, tmp_path):
        """Minimal pipeline with no Bronze files needed for unit tests."""
        pl = MedallionPipeline(
            duckdb_path=str(tmp_path / "unit.duckdb"),
            bronze_root=str(tmp_path / "empty_bronze"),
        )
        self.pl = pl
        yield
        pl.close()

    def test_usd_range(self):
        min_usd, max_usd = self.pl._parse_salary("USD 100,000 - 140,000")
        assert min_usd == pytest.approx(100000.0, abs=1)
        assert max_usd == pytest.approx(140000.0, abs=1)

    def test_usd_single_value(self):
        min_usd, max_usd = self.pl._parse_salary("USD 3500")
        assert min_usd == pytest.approx(3500.0, abs=1)
        assert max_usd is None

    def test_usd_monthly_converts_to_annual(self):
        min_usd, _ = self.pl._parse_salary("USD 3,500 mes")
        assert min_usd == pytest.approx(42000.0, abs=100)

    def test_clp_converted_to_usd(self):
        min_usd, max_usd = self.pl._parse_salary("CLP 2000000 - 3000000")
        # CLP → USD at 0.00106 rate (updated May 2026)
        assert min_usd == pytest.approx(2000000 * 0.00106, abs=10)
        assert max_usd == pytest.approx(3000000 * 0.00106, abs=10)

    def test_ars_converted_to_usd(self):
        min_usd, _ = self.pl._parse_salary("ARS 80000")
        # ARS → USD at 0.001 rate (updated May 2026)
        assert min_usd == pytest.approx(80000 * 0.001, abs=1)

    def test_none_returns_none_none(self):
        assert self.pl._parse_salary(None) == (None, None)

    def test_empty_string_returns_none_none(self):
        assert self.pl._parse_salary("") == (None, None)

    def test_unrecognized_string_returns_none_none(self):
        assert self.pl._parse_salary("negotiable") == (None, None)


# ---------------------------------------------------------------------------
# Unit tests — Location parsing
# ---------------------------------------------------------------------------

class TestLocationParsing:

    @pytest.fixture(autouse=True)
    def _pipeline(self, tmp_path):
        pl = MedallionPipeline(
            duckdb_path=str(tmp_path / "loc.duckdb"),
            bronze_root=str(tmp_path / "empty_bronze"),
        )
        self.pl = pl
        yield
        pl.close()

    def test_remote_is_remote(self):
        city, is_remote = self.pl._parse_location("Remote")
        assert is_remote is True
        assert city is None

    def test_remoto_is_remote(self):
        city, is_remote = self.pl._parse_location("Remoto")
        assert is_remote is True

    def test_city_country_extracts_city(self):
        city, is_remote = self.pl._parse_location("Santiago, Chile")
        assert city == "Santiago"
        assert is_remote is False

    def test_hybrid_extracts_city(self):
        city, is_remote = self.pl._parse_location("Hybrid - Buenos Aires")
        assert city == "Buenos Aires"
        assert is_remote is False

    def test_none_returns_none_false(self):
        city, is_remote = self.pl._parse_location(None)
        assert city is None
        assert is_remote is False


# ---------------------------------------------------------------------------
# Integration tests — Bronze → Silver
# ---------------------------------------------------------------------------

class TestBronzeToSilver:

    def test_creates_silver_jobs_table(self, pipeline):
        pipeline.run_bronze_to_silver()
        count = pipeline.conn.execute("SELECT COUNT(*) FROM silver.jobs").fetchone()[0]
        assert count > 0

    def test_row_count_matches_unique_urls(self, pipeline):
        """
        The 5 Bronze rows have 5 unique URLs, so Silver should have 5 rows.
        """
        row_count = pipeline.run_bronze_to_silver()
        assert row_count == 5

    def test_deduplication_keeps_only_one_row_per_url(self, tmp_path):
        """
        If the same URL appears in two Bronze files (two scraper runs),
        Silver should keep only one.
        """
        bronze_dir = tmp_path / "bronze" / "role=data_engineer"
        bronze_dir.mkdir(parents=True)

        # Two parquet files with overlapping URLs
        jobs = _make_sample_jobs(3)
        df1 = pd.DataFrame(jobs)
        df2 = pd.DataFrame(jobs)  # exact same URLs, later scrape
        df2["scraped_at"] = datetime(2026, 3, 29, 10, 0, 0).isoformat()  # later

        df1.to_parquet(bronze_dir / "run1.parquet", engine="pyarrow", index=False)
        df2.to_parquet(bronze_dir / "run2.parquet", engine="pyarrow", index=False)

        pl = MedallionPipeline(
            duckdb_path=str(tmp_path / "dedup.duckdb"),
            bronze_root=str(tmp_path / "bronze"),
        )
        pl.run_bronze_to_silver()

        count = pl.conn.execute("SELECT COUNT(*) FROM silver.jobs").fetchone()[0]
        pl.close()

        # 3 unique URLs, not 6, despite 6 Bronze rows
        assert count == 3

    def test_canonical_role_is_set(self, pipeline):
        pipeline.run_bronze_to_silver()
        roles = pipeline.conn.execute(
            "SELECT DISTINCT canonical_role FROM silver.jobs"
        ).fetchall()
        role_values = [r[0] for r in roles]
        assert "data_engineer" in role_values

    def test_empty_bronze_returns_zero(self, tmp_path):
        pl = MedallionPipeline(
            duckdb_path=str(tmp_path / "empty.duckdb"),
            bronze_root=str(tmp_path / "empty_bronze"),
        )
        count = pl.run_bronze_to_silver()
        pl.close()
        assert count == 0


# ---------------------------------------------------------------------------
# Integration tests — Silver → Gold
# ---------------------------------------------------------------------------

class TestSilverToGold:

    def test_all_gold_tables_are_created(self, pipeline):
        pipeline.run_bronze_to_silver()
        pipeline.run_silver_to_gold()

        tables = pipeline.conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'gold'"
        ).fetchall()
        table_names = {t[0] for t in tables}

        assert "demand_by_role" in table_names
        assert "salary_trends" in table_names
        assert "skills_frequency" in table_names

    def test_demand_by_role_has_data(self, pipeline):
        pipeline.run_full_pipeline()
        count = pipeline.conn.execute("SELECT COUNT(*) FROM gold.demand_by_role").fetchone()[0]
        assert count > 0

    def test_skills_frequency_unnests_correctly(self, pipeline):
        """
        Each Bronze job has 3 skills: Python, Spark, SQL.
        After UNNEST, skills_frequency should have at least those 3 skills.
        """
        pipeline.run_full_pipeline()
        skills = pipeline.conn.execute(
            "SELECT skill FROM gold.skills_frequency"
        ).fetchall()
        skill_names = {s[0] for s in skills}

        assert "python" in skill_names
        assert "sql" in skill_names

    def test_gold_skips_when_silver_is_empty(self, tmp_path):
        """Silver → Gold should not crash when silver.jobs is empty."""
        pl = MedallionPipeline(
            duckdb_path=str(tmp_path / "skip_gold.duckdb"),
            bronze_root=str(tmp_path / "empty_bronze"),
        )
        # Should not raise
        pl.run_bronze_to_silver()
        pl.run_silver_to_gold()
        pl.close()


# ---------------------------------------------------------------------------
# Integration tests — Full pipeline + helpers
# ---------------------------------------------------------------------------

class TestFullPipeline:

    def test_run_full_pipeline_does_not_raise(self, pipeline):
        pipeline.run_full_pipeline()  # must complete without exception

    def test_get_gold_summary_returns_counts(self, pipeline):
        pipeline.run_full_pipeline()
        summary = pipeline.get_gold_summary()

        assert "silver.jobs" in summary
        assert "gold.demand_by_role" in summary
        assert summary["silver.jobs"] > 0

    def test_query_helper_returns_dataframe(self, pipeline):
        pipeline.run_full_pipeline()
        df = pipeline.query("SELECT * FROM silver.jobs LIMIT 2")
        assert len(df) <= 2
        assert "url" in df.columns

    def test_context_manager_closes_connection(self, tmp_path, bronze_parquet):
        with MedallionPipeline(
            duckdb_path=str(tmp_path / "cm.duckdb"),
            bronze_root=str(tmp_path / "bronze"),
        ) as pl:
            pl.run_full_pipeline()
        # After __exit__, queries must fail
        with pytest.raises(Exception):
            pl.conn.execute("SELECT 1")
