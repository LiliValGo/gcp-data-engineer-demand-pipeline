/*
  Test: assert_no_duplicate_job_ids
  ─────────────────────────────────────────────────────────────────────────────
  Verifies that silver.jobs has no duplicate job_id values.

  A duplicate means the Python upsert in medallion.py failed to deduplicate
  correctly — this would silently inflate all Gold aggregations.

  Result: returns rows only when duplicates exist → test fails if rows returned.
*/

SELECT
    job_id,
    COUNT(*) AS cnt
FROM "pipeline"."silver"."jobs"
GROUP BY job_id
HAVING COUNT(*) > 1