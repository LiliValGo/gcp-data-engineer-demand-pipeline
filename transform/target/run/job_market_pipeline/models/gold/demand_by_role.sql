
  
    
    

    create  table
      "pipeline"."gold"."demand_by_role__dbt_tmp"
  
    as (
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
    CAST(scraped_at AS DATE)      AS date,
    COUNT(*)                       AS job_count,
    COUNT(DISTINCT company)        AS unique_companies,
    AVG(extraction_quality_score)  AS avg_quality_score
FROM "pipeline"."silver"."jobs"
GROUP BY
    canonical_role,
    CAST(scraped_at AS DATE)
ORDER BY
    date DESC,
    job_count DESC
    );
  
  