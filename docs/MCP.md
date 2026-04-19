# MCP Server — Job Market Pipeline

Exposes the Gold layer of the pipeline to Claude via the
[Model Context Protocol](https://modelcontextprotocol.io).
Claude can query market demand data and analyse CV skill gaps
through natural language — without writing a single line of SQL.

---

## Quick Start

```bash
# 1. Make sure the pipeline has data (scrape + medallion)
python main_scraper.py

# 2. Start the MCP server
python run_mcp.py
```

---

## Tools

### `get_available_roles`

List every canonical role in the database with its total job count.

```json
{}
```

Example response:
```json
[
  {"canonical_role": "data_engineer", "total_jobs": 42},
  {"canonical_role": "data_analyst",  "total_jobs": 18}
]
```

---

### `get_top_skills`

Most demanded skills for a role, ordered by mention count.

```json
{"role": "data_engineer", "limit": 10}
```

Example response:
```json
[
  {"skill": "python",  "mention_count": 38, "pct": 90.5},
  {"skill": "sql",     "mention_count": 32, "pct": 76.2},
  {"skill": "spark",   "mention_count": 21, "pct": 50.0}
]
```

---

### `get_demand_trends`

Daily job counts for a role over the last 30 days.

```json
{"role": "data_engineer"}
```

Example response:
```json
[
  {"date": "2026-04-18", "job_count": 5, "unique_companies": 5},
  {"date": "2026-04-17", "job_count": 3, "unique_companies": 3}
]
```

---

### `get_salary_trends`

USD salary statistics for a role, optionally filtered by city.

```json
{"role": "data_engineer"}
{"role": "data_engineer", "city": "Santiago"}
```

Example response:
```json
[
  {
    "city": "Santiago",
    "jobs_with_salary": 12,
    "min_salary_usd": 60000,
    "avg_min_salary_usd": 85000,
    "avg_max_salary_usd": 120000,
    "max_salary_usd": 160000,
    "median_min_usd": 82000
  }
]
```

---

### `compare_skills`

Compare CV skills against top market demand for a role.
Returns a gap analysis with coverage percentage.

```json
{
  "cv_skills": ["Python", "SQL", "Excel"],
  "role": "data_engineer"
}
```

Example response:
```json
{
  "skills_you_have":   ["python", "sql"],
  "skills_missing":    ["spark", "dbt", "kafka", "airflow"],
  "additional_skills": ["excel"],
  "market_coverage_pct": 40.0
}
```

---

## CV Gap Analysis Flow

Paste your CV into a Claude chat where this MCP server is connected.
Claude will:

1. Extract the skill list from the CV text.
2. Call `get_available_roles()` to confirm which role to compare against.
3. Call `get_top_skills("data_engineer")` to retrieve market demand.
4. Call `compare_skills([...], "data_engineer")` to compute the gap.
5. Call `get_salary_trends("data_engineer")` for salary context.
6. Generate a prioritised learning roadmap.

---

## Testing Without Claude Desktop — MCP Inspector

```bash
# Requires Node.js
npx @modelcontextprotocol/inspector python run_mcp.py

# Opens http://localhost:5173
# Click "Connect", then call any tool with JSON arguments.
```

---

## Claude Desktop Config (future)

Once the server is deployed to Cloud Run (Phase 4), add this block to
`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "job-market-pipeline": {
      "command": "python",
      "args": ["/absolute/path/to/run_mcp.py"]
    }
  }
}
```

---

## File Structure

```
mcp_server/
├── __init__.py     (empty — marks the package)
├── queries.py      DuckDB query functions + compare_skills logic
└── server.py       FastMCP instance + 5 tool decorators
run_mcp.py          Entry point: python run_mcp.py
tests/
└── test_mcp_tools.py   14 unit tests (102 → 116 total)
```

---

## Architecture

```
Claude (natural language)
    │
    ▼
MCP Server  mcp_server/server.py
    │  stdio transport
    ▼
mcp_server/queries.py
    │  singleton MedallionPipeline
    ▼
data/pipeline.duckdb
    ├── silver.jobs           (get_available_roles)
    ├── gold.skills_frequency (get_top_skills, compare_skills)
    ├── gold.demand_by_role   (get_demand_trends)
    └── gold.salary_trends    (get_salary_trends)
```
