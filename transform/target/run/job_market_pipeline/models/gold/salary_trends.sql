
  
    
    

    create  table
      "pipeline"."gold"."salary_trends__dbt_tmp"
  
    as (
      /*
  gold.salary_trends
  ─────────────────────────────────────────────────────────────────────────────
  Answers: "What is the salary range for each role by city?"

  Only includes jobs where salary_usd_min is not null (i.e. salary was
  successfully extracted and parsed by medallion.py).

  PERCENTILE_CONT is an ordered-set aggregate — same syntax in BigQuery.
  COALESCE(city, 'Remote/Unknown') groups remote and location-less jobs together.

  Consumed by:
    - MCP tool: get_salary_trends()

  Materialization: table (full refresh) — declared in dbt_project.yml
*/

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
FROM "pipeline"."silver"."jobs"
WHERE salary_usd_min IS NOT NULL
GROUP BY
    canonical_role,
    COALESCE(city, 'Remote/Unknown')
ORDER BY
    canonical_role,
    jobs_with_salary DESC
    );
  
  