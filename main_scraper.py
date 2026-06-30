"""Refactored main scraper script with logging, quality checks, and checkpoints"""

import logging
import sys
from datetime import datetime, timezone

from scraper.config import settings
from scraper.logging_config import setup_logging
from scraper.client import GetOnBoardClient
from scraper.parser import parse_jobs, parse_job_details
from scraper.exporter import export_jobs, DatasetLineage
from scraper.checkpoint import ScrapingCheckpoint
from scraper.quality import DataQualityValidator, ExtractionConfidenceCalculator
from role_mapper.role_mapper import RoleMapper
from scraper.medallion import MedallionPipeline


def main():
    """Main scraper orchestration"""
    
    # Initialize logging
    logger = setup_logging(
        level=settings.log_level,
        log_format=settings.log_format
    )

    logger.info("╔════════════════════════════════════════╗")
    logger.info("║  GetonBoard Job Scraper v2.0          ║")
    logger.info("║  Powered by Data Engineering         ║")
    logger.info("╚════════════════════════════════════════╝")

    try:
        # Initialize components
        client = GetOnBoardClient()
        checkpoint = ScrapingCheckpoint()
        validator = DataQualityValidator()
        role_mapper = RoleMapper("role_mapper/config/roles.yaml")

        all_jobs = []

        # Process search terms
        for term in settings.search_terms:
            logger.info(f"Processing search term: {term}")

            try:
                # Resolve canonical role for this search term once (reused in checkpoint calls)
                canonical = role_mapper.find_role(term)
                role_key = canonical.role_key if canonical else term

                # Search for jobs
                html = client.search(term)
                jobs = parse_jobs(html, term)

                logger.info(f"Found {len(jobs)} initial jobs for '{term}'")

                # Filter processed URLs
                unprocessed_urls = checkpoint.get_unprocessed_urls(
                    [job.url for job in jobs]
                )
                unique_jobs = [j for j in jobs if j.url in unprocessed_urls]
                skipped = len(jobs) - len(unique_jobs)

                logger.info(f"After deduplication: {len(unique_jobs)} new jobs ({skipped} duplicates)")

                # Process each job's details concurrently
                logger.info(f"Fetching details for {len(unique_jobs)} jobs concurrently...")
                from concurrent.futures import ThreadPoolExecutor, as_completed

                def fetch_job_html(j):
                    try:
                        html = client.get_job_details(j.url)
                        return j, html, None
                    except Exception as err:
                        return j, None, err

                job_htmls = []
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(fetch_job_html, job): job for job in unique_jobs}
                    for future in as_completed(futures):
                        job_htmls.append(future.result())

                # Process results sequentially to ensure database/logging thread safety
                for idx, (job, html, err) in enumerate(job_htmls, 1):
                    try:
                        logger.debug(f"[{idx}/{len(job_htmls)}] Processing: {job.title} @ {job.company}")
                        if err:
                            raise err

                        details = parse_job_details(html)

                        # Enrich job with details
                        job.description = details.get("description")
                        job.description_extraction_method = details.get("description_extraction_method")
                        job.description_confidence = details.get("description_confidence")
                        job.skills = details.get("skills")
                        job.skills_confidence = details.get("skills_confidence")
                        job.experience_level = details.get("experience_level")
                        job.contract_type = details.get("contract_type")
                        job.job_category = details.get("job_category")
                        job.processing_timestamp = datetime.now(timezone.utc)

                        # Validate quality
                        is_valid, errors = validator.validate_record(job.model_dump())
                        job.is_valid = is_valid
                        job.validation_errors = errors if errors else None

                        # Mark as processed
                        checkpoint.mark_processed(
                            url=job.url,
                            search_term=term,
                            role=role_key,
                            confidence_score=job.description_confidence,
                            extraction_method=job.description_extraction_method
                        )

                        all_jobs.append(job)
                        logger.debug(f"Job processed successfully: {job.title}")

                    except Exception as e:
                        logger.error(f"Error processing job {job.url}: {e}")
                        checkpoint.mark_failed(
                            url=job.url,
                            search_term=term,
                            role=role_key,
                            error_message=str(e)
                        )
                        continue

            except Exception as e:
                logger.error(f"Error processing search term '{term}': {e}", exc_info=True)
                continue

        # Quality analysis
        logger.info(f"\nValidating {len(all_jobs)} jobs...")
        quality_report = validator.validate_batch([j.model_dump() for j in all_jobs])

        logger.info(f"Quality Report:")
        logger.info(f"  Valid records: {quality_report.metrics.valid_records}")
        logger.info(f"  Invalid records: {quality_report.metrics.invalid_records}")
        logger.info(f"  Average confidence: {quality_report.metrics.avg_confidence:.2f}")
        logger.info(f"  Null description rate: {quality_report.metrics.null_description_rate:.2%}")

        # Export to Bronze layer (Parquet)
        logger.info(f"\nExporting {len(all_jobs)} jobs to Bronze layer (Parquet)...")

        lineage = DatasetLineage(
            source_url="https://www.getonbrd.com/jobs",
            source_type="web_scrape",
            extraction_method="getonboard_scraper_v2",
            extraction_timestamp=datetime.now(timezone.utc).isoformat(),
            record_count=len(all_jobs),
            schema_version="JobV2",
            data_quality_metrics=quality_report.metrics.__dict__,
            owner="data-engineering@company.com"
        )

        output_file = export_jobs(all_jobs, role="data_engineer", lineage=lineage)
        logger.info(f"Bronze layer written: {output_file}")

        # Run Medallion pipeline: Bronze → Silver → Gold
        logger.info("\nRunning Medallion pipeline (Bronze → Silver → Gold)...")
        pipeline = MedallionPipeline()
        pipeline.run_full_pipeline()
        gold_summary = pipeline.get_gold_summary()
        logger.info(f"Gold layer summary: {gold_summary}")
        logger.info(f"\n╔════════════════════════════════════════╗")
        logger.info(f"║  Scraping completed successfully       ║")
        logger.info(f"║  Total jobs: {len(all_jobs):27} │")
        logger.info(f"║  Valid jobs: {quality_report.metrics.valid_records:28} │")
        logger.info(f"║  Bronze: {output_file:30} │")
        logger.info(f"╚════════════════════════════════════════╝")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    finally:
        try:
            if 'client' in locals():
                client.close()
            if 'checkpoint' in locals():
                checkpoint.close()
            if 'pipeline' in locals():
                pipeline.close()
        except Exception as cleanup_error:
            logger.warning(f"Error during cleanup: {cleanup_error}")


if __name__ == "__main__":
    main()
