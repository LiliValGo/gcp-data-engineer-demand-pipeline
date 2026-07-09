# GCP Data Engineer Demand Pipeline

A production-grade web scraping pipeline that tracks demand for data engineering roles in the Latin American job market. Targets [GetonBoard.com](https://www.getonbrd.com).

Built as a learning project for senior data engineering patterns — runs locally, and integrates with an MCP Server for real-time querying.

---

## Architecture

```
Scraper (GetonBoard)
    │
    ▼
Bronze  ── raw, immutable Parquet files
    │      data/bronze/role=data_engineer/2026-04-06T14-30-00__v2.parquet
    ▼
Silver  ── cleaned, deduplicated DuckDB table
    │      silver.jobs  (salary normalized, location parsed, canonical role)
    ▼
Gold    ── analytics aggregation tables
           gold.demand_by_role    daily job counts
           gold.salary_trends     salary percentiles per city
           gold.skills_frequency  top skills frequency
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the system architecture.
See [docs/MEDALLION.md](docs/MEDALLION.md) for the Medallion layer reference.
See [docs/MCP.md](docs/MCP.md) for the MCP Server tools.

---

## Features

- **Medallion Architecture** (Bronze / Silver / Gold) — mirrors BigQuery lake-house patterns
- **DuckDB** as the local analytics engine (~90% BigQuery SQL compatible)
- **Parquet output** with Snappy compression (columnar, predicate-pushdown ready)
- **Checkpoint system** — idempotent scraping; resumes without re-processing URLs
- **Data Quality Framework** — confidence scoring per extraction method
- **Role Mapper** — fuzzy-matched canonical role normalization for Data Engineers
- **Schema versioning** — `JobV1` → `JobV2` with no breaking changes
- **MCP Server** — Claude queries Gold layer and triggers real-time scraping via Model Context Protocol (6 tools)
- **CV Gap Analysis** — paste a CV, get skill coverage % and learning roadmap
- **Structured JSON logging** — ready for Cloud Logging ingestion

---

## Quick Start

```bash
# 1. Create and activate virtual environment
python -m venv venv && source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run full pipeline (scrape + Bronze + Silver + Gold)
python main_scraper.py

# 4. Start the MCP Server (Claude queries Gold layer)
# Standard stdio mode:
python run_mcp.py

# SSE Mode (Recommended for macOS sandbox bypass, runs on port 8000):
# MCP_TRANSPORT=sse PORT=8000 python run_mcp.py
```

---

## Project Structure

```
├── scraper/
│   ├── models.py         # JobV2 Pydantic schema
│   ├── client.py         # HTTP client with retry / circuit-breaker
│   ├── parser.py         # BeautifulSoup HTML parsing
│   ├── exporter.py       # Bronze Parquet writer
│   ├── checkpoint.py     # DuckDB-backed idempotency store
│   ├── quality.py        # Data quality rules + confidence scoring
│   ├── medallion.py      # Bronze → Silver → Gold transformations
│   ├── config.py         # Pydantic Settings
│   └── logging_config.py # Structured JSON logging setup
├── mcp_server/
│   ├── queries.py        # DuckDB query functions (Gold layer)
│   └── server.py         # FastMCP + 6 tools (including on-demand scrape)
├── role_mapper/
│   ├── role_mapper.py    # Fuzzy + keyword role matching
│   └── config/roles.yaml # Role definition (variants, keywords, hierarchy)
├── tests/                # Unit and integration tests (pytest)
├── docs/
│   ├── ARCHITECTURE.md   # System architecture
│   ├── MEDALLION.md      # Medallion layer reference
│   └── MCP.md            # MCP Server tools + CV gap analysis guide
├── main_scraper.py       # CLI entry point
├── run_mcp.py            # MCP Server entry point
├── scripts/
│   ├── seed_demo_data.py  # Dev utility: seed Silver + Gold with Data Engineer demo rows
│   ├── test_mcp_direct.py # Dev utility: smoke-test all 6 MCP tools via JSON-RPC
│   └── query_db.py        # Dev utility: run SQL queries on DuckDB
└── requirements.txt
```

---

## Running Tests

```bash
source venv/bin/activate
pytest tests/ -v
```

---

## Output Files

| Path | Description |
|------|-------------|
| `data/bronze/role={role}/{timestamp}__v2.parquet` | Raw scraped jobs (immutable) |
| `data/bronze/role={role}/{timestamp}__v2.metadata.json` | Lineage + quality metrics |
| `data/pipeline.duckdb` | Silver + Gold DuckDB tables |
| `data/.checkpoints/urls.db` | Processed URL checkpoint store |

---

## Querying Gold Data

Use the custom Python terminal interface to run SQL:

```bash
python scripts/query_db.py
```

Example queries:
```sql
-- Top demanded roles
SELECT * FROM gold.demand_by_role ORDER BY date DESC, job_count DESC LIMIT 10;

-- Salary distribution for data engineers
SELECT * FROM gold.salary_trends WHERE canonical_role = 'data_engineer';

-- Most-mentioned skills
SELECT skill, mention_count
FROM gold.skills_frequency
WHERE canonical_role = 'data_engineer'
ORDER BY mention_count DESC
LIMIT 15;
```
