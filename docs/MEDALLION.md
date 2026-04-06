# Medallion Architecture

This document describes the Bronze → Silver → Gold data pipeline implemented in
`scraper/medallion.py`. The pattern mirrors production BigQuery/Spark lake-house
architectures, making local development directly transferable to GCP.

---

## Overview

```
Scraper
  │
  ▼
Bronze  (raw, immutable Parquet files on disk)
  │  data/bronze/role=data_engineer/2026-04-06T14-30-00__v2.parquet
  │
  ▼
Silver  (cleaned, deduplicated DuckDB table)
  │  silver.jobs  — salary normalized, location parsed, canonical role assigned
  │
  ▼
Gold    (analytics-ready aggregation tables)
       gold.demand_by_role    — daily job counts per role
       gold.salary_trends     — salary percentiles per role / city
       gold.skills_frequency  — top skills per role
```

---

## Bronze Layer — Raw Data

| Property       | Value                                          |
|----------------|------------------------------------------------|
| Location       | `data/bronze/role={role}/`                     |
| Format         | Parquet (Snappy compression, PyArrow engine)   |
| Schema         | `JobV2` Pydantic model serialized as-is        |
| Partitioning   | By `role` (Hive-style directory naming)        |
| Immutability   | Each scraper run produces a timestamped file   |

### File naming convention

```
data/bronze/
└── role=data_engineer/
    ├── 2026-04-06T14-30-00__v2.parquet
    ├── 2026-04-06T14-30-00__v2.metadata.json   ← lineage / provenance
    ├── 2026-04-06T18-15-00__v2.parquet
    └── 2026-04-06T18-15-00__v2.metadata.json
```

The companion `.metadata.json` stores `DatasetLineage` (source URL, extraction
method, record count, data quality metrics, schema version) without bloating the
Parquet file itself.

### Why Parquet instead of JSON?

- **Columnar storage**: predicate pushdown when DuckDB reads it (`WHERE role = ?`)
- **Compression**: Snappy reduces file size ~60-70 % vs. JSON
- **Schema enforcement**: PyArrow validates column types at write time
- **BigQuery compatibility**: External Tables read Parquet natively

---

## Silver Layer — Cleaned Data

| Property   | Value                                              |
|------------|----------------------------------------------------|
| Location   | `data/pipeline.duckdb` → schema `silver`           |
| Table      | `silver.jobs`                                      |
| Primary key| `job_id` (MD5 of `url`)                            |

### Transformations applied

| Input (Bronze)              | Output (Silver)                         |
|-----------------------------|-----------------------------------------|
| `salary` (free-text string) | `salary_usd_min`, `salary_usd_max` (DOUBLE) |
| `location` (free-text)      | `city` (VARCHAR), `is_remote` (BOOLEAN) |
| `search_term`               | `canonical_role` via `RoleMapper`       |
| Duplicate URLs (multi-run)  | Deduplicated — latest `scraped_at` wins |
| `skills` JSON array         | `skills VARCHAR[]` (DuckDB native list) |

#### Salary normalization

Exchange rates are hardcoded (suitable for MVP; add a rates API in Phase 4):

| Currency | Rate to USD |
|----------|-------------|
| CLP      | 0.0011      |
| ARS      | 0.0012      |
| MXN      | 0.058       |
| USD      | 1.0 (base)  |

Monthly salaries are annualized (`× 12`).

#### Deduplication strategy

```sql
ROW_NUMBER() OVER (PARTITION BY url ORDER BY scraped_at DESC) AS rn
-- WHERE rn = 1  →  keeps only the most recent scrape per URL
```

This mirrors the BigQuery `MERGE` / `QUALIFY ROW_NUMBER()` patterns used in
production.

---

## Gold Layer — Analytics Tables

All three tables are refreshed with `CREATE OR REPLACE TABLE` on every pipeline
run. Full refresh is fast for datasets under ~1 M rows; switch to incremental
`INSERT/MERGE` in Phase 4.

### `gold.demand_by_role`

Daily job counts per canonical role.

```sql
SELECT
    canonical_role,
    DATE_TRUNC('day', scraped_at) AS date,
    COUNT(*)                      AS job_count,
    COUNT(DISTINCT company)       AS unique_companies
FROM silver.jobs
GROUP BY canonical_role, DATE_TRUNC('day', scraped_at)
```

### `gold.salary_trends`

Salary distribution statistics per role and city.

```sql
SELECT
    canonical_role,
    city,
    COUNT(*)                                                 AS jobs_with_salary,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY salary_usd_min) AS p25_min,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY salary_usd_min) AS median_min,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY salary_usd_max) AS p75_max
FROM silver.jobs
WHERE salary_usd_min IS NOT NULL
GROUP BY canonical_role, city
```

### `gold.skills_frequency`

Top skills per role, derived by unnesting the `skills` array.

```sql
SELECT
    canonical_role,
    UNNEST(skills) AS skill,
    COUNT(*)       AS mention_count
FROM silver.jobs
WHERE skills IS NOT NULL
GROUP BY canonical_role, skill
ORDER BY mention_count DESC
```

---

## Running the Pipeline

```bash
# Full pipeline: scrape + Bronze + Silver + Gold
python main_scraper.py

# Run only the Medallion transformations (Bronze → Silver → Gold)
python -c "
from scraper.medallion import MedallionPipeline
with MedallionPipeline() as p:
    p.run_full_pipeline()
    print(p.get_gold_summary())
"

# Query Gold tables interactively
duckdb data/pipeline.duckdb
> SELECT * FROM gold.demand_by_role ORDER BY date DESC LIMIT 10;
> SELECT * FROM gold.salary_trends WHERE canonical_role = 'data_engineer' LIMIT 5;
> SELECT * FROM gold.skills_frequency ORDER BY mention_count DESC LIMIT 10;
```

---

## Idempotency Guarantee

Running the scraper twice on the same day is safe:

1. **Bronze**: two timestamped Parquet files are created (immutable, append-only).
2. **Checkpoint** (`data/.checkpoints/urls.db`): DuckDB upsert prevents
   re-fetching URLs already scraped in a previous run.
3. **Silver**: deduplication by URL keeps only the most recent record.
4. **Gold**: `CREATE OR REPLACE TABLE` rebuilds from the current Silver state.

---

## Mapping to GCP Services (Future — Phase 4)

| Local component           | GCP equivalent                          |
|---------------------------|-----------------------------------------|
| `data/bronze/`            | Cloud Storage bucket (GCS)              |
| `data/pipeline.duckdb`    | BigQuery dataset                        |
| `silver.jobs`             | BigQuery managed table                  |
| `gold.*` tables           | BigQuery views or materialized tables   |
| `main_scraper.py` cron    | Cloud Scheduler + Cloud Run job         |
| DuckDB SQL                | BigQuery SQL (~90 % compatible)         |
