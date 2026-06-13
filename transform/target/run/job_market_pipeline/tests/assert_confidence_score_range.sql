select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      /*
  Test: assert_confidence_score_range
  ─────────────────────────────────────────────────────────────────────────────
  Verifies that extraction_quality_score is within [0.0, 1.0] for all rows
  where it is not null.

  A value outside this range indicates a bug in scraper/quality.py
  (ExtractionConfidenceCalculator) that is leaking into Silver and would
  corrupt avg_quality_score in gold.demand_by_role.

  Result: returns rows only when a score is out of range → test fails if rows returned.
*/

SELECT
    job_id,
    extraction_quality_score
FROM "pipeline"."silver"."jobs"
WHERE
    extraction_quality_score IS NOT NULL
    AND (
        extraction_quality_score < 0.0
        OR extraction_quality_score > 1.0
    )
      
    ) dbt_internal_test