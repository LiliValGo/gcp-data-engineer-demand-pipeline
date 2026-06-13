/*
  gold.skills_frequency
  ─────────────────────────────────────────────────────────────────────────────
  Answers: "What % of jobs for each role mention each skill?"

  Two-step logic via CTEs:
    1. skills_unnested: UNNEST the VARCHAR[] skills array into one row per skill
    2. role_job_counts: count distinct jobs per role (the denominator for %)

  pct_of_role_jobs = COUNT(DISTINCT job_id mentioning skill)
                     ─────────────────────────────────────── × 100
                     COUNT(DISTINCT job_id for that role)

  This gives "% of jobs that require this skill" — not "% of skill mentions"
  (the previous formula in medallion.py used the latter, which was misleading).

  Consumed by:
    - MCP tool: get_top_skills(), compare_skills()

  Materialization: table (full refresh) — declared in dbt_project.yml
  BigQuery Phase 4: UNNEST syntax is identical.
*/

WITH skills_unnested AS (
    SELECT
        job_id,
        canonical_role,
        LOWER(TRIM(skill)) AS skill
    FROM {{ source('silver', 'jobs') }},
        LATERAL UNNEST(skills) AS t(skill)
    WHERE skills IS NOT NULL
),

role_job_counts AS (
    SELECT
        canonical_role,
        COUNT(DISTINCT job_id) AS total_jobs_with_skills
    FROM {{ source('silver', 'jobs') }}
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
FROM skills_unnested AS su
JOIN role_job_counts AS rjc
    USING (canonical_role)
GROUP BY
    su.canonical_role,
    su.skill,
    rjc.total_jobs_with_skills
ORDER BY
    su.canonical_role,
    mention_count DESC
