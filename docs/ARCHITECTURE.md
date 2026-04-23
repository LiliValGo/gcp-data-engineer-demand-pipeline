# System Architecture

Full architecture covering local development and GCP production across all phases.

---

## Local Architecture (Phases 0 → 3)

```
┌─────────────────────────────────────────────────────────────────────┐
│  INGEST                                                             │
│                                                                     │
│  [GetonBoard.com]                                                   │
│       │ HTTP (retry + circuit breaker)      scraper/client.py      │
│       ▼                                                             │
│  [Scraper]                                                          │
│       ├── parser.py          BeautifulSoup HTML extraction          │
│       ├── quality.py         confidence scoring (0.0 → 1.0)        │
│       ├── role_mapper/       fuzzy canonical role normalization     │
│       └── checkpoint.py      DuckDB idempotency store              │
│               │              data/.checkpoints/urls.db             │
└───────────────┼─────────────────────────────────────────────────────┘
                │ Parquet (Snappy)
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  BRONZE LAYER  (raw, immutable)                                     │
│                                                                     │
│  data/bronze/role=data_engineer/2026-04-09T10-00-00__v2.parquet    │
│  data/bronze/role=data_engineer/2026-04-09T10-00-00__v2.metadata.json│
│                                                                     │
│  Hive-style partitioning → BigQuery External Tables compatible      │
└───────────────┬─────────────────────────────────────────────────────┘
                │ medallion.py (Python now)
                │ dbt models   (Phase 3 — you build this)
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SILVER LAYER  (cleaned, deduplicated)           pipeline.duckdb   │
│                                                                     │
│  silver.jobs                                                        │
│       ├── job_id (MD5 of URL)                                       │
│       ├── canonical_role      ← normalized by RoleMapper            │
│       ├── salary_usd_min/max  ← parsed + currency converted        │
│       ├── city, is_remote     ← parsed from location string        │
│       └── extraction_quality_score                                  │
└───────────────┬─────────────────────────────────────────────────────┘
                │ dbt models (Phase 3 — you build this)
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  GOLD LAYER  (analytics-ready)                   pipeline.duckdb   │
│                                                                     │
│  gold.demand_by_role     daily job counts per role                  │
│  gold.salary_trends      salary percentiles per role / city        │
│  gold.skills_frequency   top skills per role                        │
└──────────────┬──────────────────────────┬───────────────────────────┘
               │                          │
               ▼                          ▼
┌──────────────────────┐     ┌────────────────────────────┐
│  MCP SERVER          │     │  FastAPI Web App           │
│  Phase 2             │     │  web/app.py + routes.py    │
│                      │     │                            │
│  Claude queries:     │     │  GET /roles                │
│  "top skills this    │     │  GET /jobs                 │
│   month?"            │     │  POST /scrape              │
│  "avg salary DE      │     │                            │
│   remote?"           │     │  localhost:8000            │
└──────────────────────┘     └────────────────────────────┘
```

---

## GCP Production Architecture (Phase 4)

```
┌─────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATION                                                      │
│                                                                     │
│  [Cloud Scheduler]  ──── cron: "0 6 * * *" ────►  triggers         │
│                                                         │           │
│                          [GitHub Actions]               │           │
│                          test → build → deploy          │           │
└─────────────────────────────────────────────────────────┼───────────┘
                                                          │
                                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  COMPUTE                                                            │
│                                                                     │
│  [Cloud Run Job]      ◄── Scraper container                        │
│       │                   same scraper/ code, no changes needed    │
│       │                                                             │
│  [Cloud Run Service]  ◄── MCP Server + FastAPI container           │
│       │                                                             │
│  Container images in [Artifact Registry]                           │
└───────┬──────────────────────────────────────────┬──────────────────┘
        │ write Parquet                             │ serve
        ▼                                           ▼
┌───────────────────────┐               ┌───────────────────────────┐
│  STORAGE              │               │  CONSUMERS                │
│                       │               │                           │
│  [Cloud Storage GCS]  │               │  Claude (via MCP)         │
│  gs://pipeline-bronze/│               │  REST API clients         │
│  role=data_engineer/  │               │  Looker Studio (future)   │
│       │               │               └───────────────────────────┘
│       │ dbt Core      │
│       │ (Phase 3)     │
│       ▼               │
│  [BigQuery]           │
│  dataset: silver      │
│    └── table: jobs    │
│  dataset: gold        │
│    ├── demand_by_role │
│    ├── salary_trends  │
│    └── skills_freq    │
└───────────────────────┘
        ▲
        │  manages ALL resources
┌───────────────────────┐
│  INFRASTRUCTURE       │
│                       │
│  [Terraform]          │
│  ├── GCS buckets      │
│  ├── BigQuery datasets│
│  ├── Cloud Run svcs   │
│  ├── Cloud Scheduler  │
│  └── IAM + secrets    │
│                       │
│  [Secret Manager]     │
│  API keys, env vars   │
│                       │
│  [Cloud Logging]      │
│  structured JSON logs │
│  from all services    │
└───────────────────────┘
```

---

## Technology Map: Local → GCP

| Local component             | GCP equivalent                | Phase |
|-----------------------------|-------------------------------|-------|
| `data/bronze/` (Parquet)    | Cloud Storage (GCS)           | 4     |
| `data/pipeline.duckdb`      | BigQuery dataset              | 4     |
| `silver.jobs`               | BigQuery managed table        | 4     |
| `gold.*` tables             | BigQuery views / materialized | 4     |
| `medallion.py` SQL          | dbt models                    | 3     |
| `main_scraper.py` cron      | Cloud Scheduler + Cloud Run   | 4     |
| DuckDB SQL                  | BigQuery SQL (~90% compat.)   | 4     |
| manual infra setup          | Terraform + GitHub Actions    | 3→4   |
| `python run_web.py`         | Cloud Run Service             | 4     |

---

## dbt Integration (Phase 3)

dbt replaces the Python SQL in `medallion.py` for Silver → Gold transformations.
The same models run against DuckDB locally and BigQuery in production —
zero code changes, only a profile switch.

```
transform/
├── dbt_project.yml
├── profiles.yml                   ← DuckDB locally, BigQuery in prod
├── models/
│   ├── silver/
│   │   └── jobs.sql               ← replaces run_bronze_to_silver()
│   └── gold/
│       ├── demand_by_role.sql     ← replaces gold CREATE TABLE
│       ├── salary_trends.sql
│       └── skills_frequency.sql
└── tests/
    ├── assert_no_duplicate_urls.sql
    └── assert_confidence_score_range.sql
```

---

## Terraform Scope (Phase 4)

```
infra/
├── main.tf           ← provider config (google)
├── variables.tf      ← project_id, region, environment
├── outputs.tf        ← bucket URLs, dataset IDs
└── modules/
    ├── storage/      ← GCS Bronze bucket
    ├── bigquery/     ← datasets: silver, gold
    ├── cloud_run/    ← scraper job + MCP/API service
    └── scheduler/    ← daily cron trigger
```

---

## Phase Roadmap

| Phase | Status  | Deliverable                                     |
|-------|---------|-------------------------------------------------|
| 0     | Done    | Foundation: tests, quality framework, router    |
| 1     | Done    | Bronze/Silver/Gold, DuckDB, Parquet             |
| 2     | Done    | MCP Server — Claude queries Gold layer          |
| 3     | Planned | dbt models + Makefile + GitHub Actions CI       |
| 4     | Planned | GCP: GCS + BigQuery + Cloud Run + Terraform     |
