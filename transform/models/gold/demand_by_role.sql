/*
  gold.demand_by_role
  ─────────────────────────────────────────────────────────────────────────────
  Answers: "How many jobs are posted per role per day?"

  Consumed by:
    - MCP tool: get_demand_trends()
    - FastAPI: future /api/market endpoint (Phase 3)

  Materialization: table (full refresh) — declared in dbt_project.yml
  BigQuery Phase 4: same SQL, zero changes needed.
*/

SELECT
    canonical_role,
    {% if target.type == 'bigquery' %}
    CAST(CAST(scraped_at AS TIMESTAMP) AS DATE) AS date,
    {% else %}
    CAST(scraped_at AS DATE)      AS date,
    {% endif %}
    COUNT(*)                       AS job_count,
    COUNT(DISTINCT company)        AS unique_companies,
    AVG(extraction_quality_score)  AS avg_quality_score
FROM {{ source('silver', 'jobs') }}
GROUP BY
    canonical_role,
    {% if target.type == 'bigquery' %}
    CAST(CAST(scraped_at AS TIMESTAMP) AS DATE)
    {% else %}
    CAST(scraped_at AS DATE)
    {% endif %}
ORDER BY
    date DESC,
    job_count DESC
