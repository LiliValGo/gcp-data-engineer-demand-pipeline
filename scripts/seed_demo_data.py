"""
Seed demo data into data/pipeline.duckdb so the MCP tools return real results.

Run once:
    python scripts/seed_demo_data.py

This does NOT scrape the web — it inserts a handful of realistic job rows
straight into silver.jobs, then builds the Gold layer from them.
"""

import sys
from datetime import datetime
import pandas as pd

sys.path.insert(0, ".")

from scraper.medallion import MedallionPipeline

DB_PATH = "data/pipeline.duckdb"

DEMO_JOBS = [
    {
        "job_id": "demo_de_001",
        "url": "https://getonbrd.com/jobs/demo-de-001",
        "title": "Data Engineer",
        "company": "Acme Corp",
        "canonical_role": "data_engineer",
        "search_term": "data engineer",
        "location": "Santiago, Chile",
        "city": "Santiago",
        "is_remote": False,
        "salary_raw": "USD 90,000 - 130,000",
        "salary_usd_min": 90000.0,
        "salary_usd_max": 130000.0,
        "description": "Build and maintain data pipelines.",
        "skills": ["python", "sql", "spark", "airflow", "dbt"],
        "experience_level": "mid",
        "contract_type": "full-time",
        "job_category": "Data",
        "extraction_quality_score": 0.92,
        "scraped_at": datetime(2026, 4, 15, 10, 0, 0),
        "processing_timestamp": datetime(2026, 4, 20, 0, 0, 0),
        "bronze_file_path": "demo",
    },
    {
        "job_id": "demo_de_002",
        "url": "https://getonbrd.com/jobs/demo-de-002",
        "title": "Senior Data Engineer",
        "company": "TechLatam",
        "canonical_role": "data_engineer",
        "search_term": "data engineer",
        "location": "Remote",
        "city": None,
        "is_remote": True,
        "salary_raw": "USD 100,000 - 150,000",
        "salary_usd_min": 100000.0,
        "salary_usd_max": 150000.0,
        "description": "Lead data platform initiatives.",
        "skills": ["python", "kafka", "spark", "kubernetes", "dbt"],
        "experience_level": "senior",
        "contract_type": "full-time",
        "job_category": "Data",
        "extraction_quality_score": 0.88,
        "scraped_at": datetime(2026, 4, 15, 11, 0, 0),
        "processing_timestamp": datetime(2026, 4, 20, 0, 0, 0),
        "bronze_file_path": "demo",
    },
    {
        "job_id": "demo_de_003",
        "url": "https://getonbrd.com/jobs/demo-de-003",
        "title": "Data Engineer",
        "company": "Startups Inc",
        "canonical_role": "data_engineer",
        "search_term": "data engineer",
        "location": "Santiago, Chile",
        "city": "Santiago",
        "is_remote": False,
        "salary_raw": "USD 80,000 - 110,000",
        "salary_usd_min": 80000.0,
        "salary_usd_max": 110000.0,
        "description": "Design ETL pipelines and data models.",
        "skills": ["python", "sql", "dbt", "bigquery", "airflow"],
        "experience_level": "mid",
        "contract_type": "full-time",
        "job_category": "Data",
        "extraction_quality_score": 0.85,
        "scraped_at": datetime(2026, 4, 16, 9, 0, 0),
        "processing_timestamp": datetime(2026, 4, 20, 0, 0, 0),
        "bronze_file_path": "demo",
    },
    {
        "job_id": "demo_de_004",
        "url": "https://getonbrd.com/jobs/demo-de-004",
        "title": "Data Engineer",
        "company": "Global Analytics",
        "canonical_role": "data_engineer",
        "search_term": "data engineer",
        "location": "Buenos Aires, Argentina",
        "city": "Buenos Aires",
        "is_remote": False,
        "salary_raw": None,
        "salary_usd_min": None,
        "salary_usd_max": None,
        "description": "Work on data warehouse and BI solutions.",
        "skills": ["python", "sql", "spark", "redshift"],
        "experience_level": "junior",
        "contract_type": "full-time",
        "job_category": "Data",
        "extraction_quality_score": 0.78,
        "scraped_at": datetime(2026, 4, 16, 14, 0, 0),
        "processing_timestamp": datetime(2026, 4, 20, 0, 0, 0),
        "bronze_file_path": "demo",
    },
    {
        "job_id": "demo_de_005",
        "url": "https://getonbrd.com/jobs/demo-de-005",
        "title": "ML Data Engineer",
        "company": "AI Ventures",
        "canonical_role": "data_engineer",
        "search_term": "data engineer",
        "location": "Remote",
        "city": None,
        "is_remote": True,
        "salary_raw": "USD 120,000 - 180,000",
        "salary_usd_min": 120000.0,
        "salary_usd_max": 180000.0,
        "description": "Build ML pipelines and feature stores.",
        "skills": ["python", "spark", "kafka", "mlflow", "airflow", "dbt"],
        "experience_level": "senior",
        "contract_type": "full-time",
        "job_category": "Data",
        "extraction_quality_score": 0.91,
        "scraped_at": datetime(2026, 4, 17, 8, 0, 0),
        "processing_timestamp": datetime(2026, 4, 20, 0, 0, 0),
        "bronze_file_path": "demo",
    },
]


def main():
    pipeline = MedallionPipeline(duckdb_path=DB_PATH)
    conn = pipeline.conn

    # Check how many rows already exist
    existing = conn.execute("SELECT COUNT(*) FROM silver.jobs WHERE job_id LIKE 'demo_%'").fetchone()[0]
    if existing > 0:
        print(f"Demo data already loaded ({existing} rows). Skipping insert.")
    else:
        df = pd.DataFrame(DEMO_JOBS)
        conn.register("_demo", df)
        conn.execute("""
            INSERT INTO silver.jobs
            SELECT
                job_id, url, title, company, canonical_role, search_term,
                location, city, is_remote, salary_raw, salary_usd_min,
                salary_usd_max, description, skills, experience_level,
                contract_type, job_category, extraction_quality_score,
                TRY_CAST(scraped_at AS TIMESTAMP),
                TRY_CAST(processing_timestamp AS TIMESTAMP),
                bronze_file_path
            FROM _demo
        """)
        conn.conn.commit() if hasattr(conn, 'conn') and hasattr(conn.conn, 'commit') else None
        conn.unregister("_demo")
        print(f"Inserted {len(DEMO_JOBS)} demo rows into silver.jobs.")

    # Rebuild Gold tables
    print("Building Gold layer...")
    pipeline.run_silver_to_gold()

    # Verify
    for table in ["demand_by_role", "salary_trends", "skills_frequency"]:
        count = conn.execute(f"SELECT COUNT(*) FROM gold.{table}").fetchone()[0]
        print(f"  gold.{table}: {count} rows")

    total_silver = conn.execute("SELECT COUNT(*) FROM silver.jobs").fetchone()[0]
    print(f"\nsilver.jobs total: {total_silver} rows")
    print("Done. Run python scripts/test_mcp_direct.py to test all MCP tools.")


if __name__ == "__main__":
    main()
