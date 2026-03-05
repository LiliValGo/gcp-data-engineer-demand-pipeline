#!/usr/bin/env python3
"""
Complete demo: Executes full pipeline with mock data to showcase all refactoring patterns
- Structured logging (JSON)
- Data quality framework
- Checkpoint system
- Schema versioning
- Role mapper
- Export with lineage
"""

import sys
import json
from datetime import datetime
from pathlib import Path

# Import our refactored components
from scraper.config import settings
from scraper.logging_config import setup_logging
from scraper.models import JobV2
from scraper.parser import parse_job_details
from scraper.exporter import export_jobs, DatasetLineage
from scraper.checkpoint import ScrapingCheckpoint
from scraper.quality import DataQualityValidator, ExtractionConfidenceCalculator, ExtractionMethod
from role_mapper.role_mapper import RoleMapper

# Setup logging
logger = setup_logging(level="INFO", log_format="json")

def create_mock_jobs():
    """Create mock job data for demo"""
    mock_jobs = [
        {
            "title": "Senior Data Engineer",
            "company": "TechCorp",
            "location": "Remote",
            "salary": "USD 120,000 - 180,000",
            "url": "https://getonbrd.com/jobs/1",
            "search_term": "data engineer",
            "description": "We are looking for a Senior Data Engineer to build scalable data pipelines using Python, Apache Spark, and AWS. You will design and maintain ETL processes, work with big data technologies, and collaborate with data scientists. Requirements: 5+ years experience, proficiency in Python, knowledge of cloud platforms.",
            "skills": ["Python", "Apache Spark", "AWS", "SQL", "Kafka", "Docker"],
            "experience_level": "Senior",
            "contract_type": "full-time",
            "job_category": "Data Engineering",
        },
        {
            "title": "Data Analyst",
            "company": "Analytics Inc",
            "location": "Buenos Aires",
            "salary": "ARS 80,000 - 120,000",
            "url": "https://getonbrd.com/jobs/2",
            "search_term": "data analyst",
            "description": "Join our analytics team to transform business data into actionable insights. Responsibilities include creating dashboards, analyzing trends, and presenting findings to stakeholders. You will work with SQL, Tableau, and Python to drive data-driven decisions.",
            "skills": ["SQL", "Tableau", "Python", "Excel", "Statistics"],
            "experience_level": "Mid",
            "contract_type": "full-time",
            "job_category": "Analytics",
        },
        {
            "title": "ML Engineer - Computer Vision",
            "company": "AI Ventures",
            "location": "Santiago",
            "salary": "USD 100,000 - 150,000",
            "url": "https://getonbrd.com/jobs/3",
            "search_term": "data scientist",
            "description": "Build and deploy computer vision models for real-world applications. We use TensorFlow, PyTorch, and deploy on AWS. You will work on image classification, object detection, and real-time processing systems.",
            "skills": ["Python", "TensorFlow", "PyTorch", "Computer Vision", "AWS"],
            "experience_level": "Senior",
            "contract_type": "full-time",
            "job_category": "Data Science",
        },
    ]
    
    jobs = []
    for job_data in mock_jobs:
        job = JobV2(
            **job_data,
            description_extraction_method=ExtractionMethod.CLASS_SEARCH.value,
            description_confidence=0.85,
            skills_confidence=0.90,
            extraction_quality_score=0.87,
            is_valid=True,
            scraped_at=datetime.utcnow(),
        )
        jobs.append(job)
    
    return jobs

def main():
    logger.info("╔════════════════════════════════════════╗")
    logger.info("║   START: Complete Pipeline Demo        ║")
    logger.info("║   Showcasing Senior-Level Refactoring  ║")
    logger.info("╚════════════════════════════════════════╝")
    
    try:
        # =================================================================
        # 1. CREATE MOCK DATA
        # =================================================================
        logger.info("step_1_create_mock_data", extra={"extra_data": {"action": "Creating mock job data"}})
        jobs = create_mock_jobs()
        logger.info("jobs_created", extra={"extra_data": {"count": len(jobs)}})
        
        # =================================================================
        # 2. DATA QUALITY VALIDATION
        # =================================================================
        logger.info("step_2_quality_validation", extra={"extra_data": {"action": "Validating data quality"}})
        validator = DataQualityValidator()
        quality_report = validator.validate_batch([j.model_dump() for j in jobs])
        
        logger.info("quality_check_completed", extra={
            "extra_data": {
                "valid_records": quality_report.metrics.valid_records,
                "invalid_records": quality_report.metrics.invalid_records,
                "avg_confidence": f"{quality_report.metrics.avg_confidence:.2f}",
            }
        })
        
        # =================================================================
        # 3. CHECKPOINT SYSTEM (Idempotency)
        # =================================================================
        logger.info("step_3_checkpoint_system", extra={"extra_data": {"action": "Testing checkpoint deduplication"}})
        checkpoint = ScrapingCheckpoint()
        
        processed_count = 0
        for job in jobs:
            if not checkpoint.is_processed(job.url):
                checkpoint.mark_processed(
                    url=job.url,
                    search_term=job.search_term,
                    role="data_engineer",
                    confidence_score=job.description_confidence,
                    extraction_method=job.description_extraction_method
                )
                processed_count += 1
        
        logger.info("checkpoint_recorded", extra={"extra_data": {"processed_count": processed_count}})
        
        # Test deduplication
        stats = checkpoint.get_stats(role="data_engineer")
        logger.info("checkpoint_stats", extra={"extra_data": stats})
        
        # =================================================================
        # 4. ROLE MAPPER (Search variants)
        # =================================================================
        logger.info("step_4_role_mapper", extra={"extra_data": {"action": "Testing role search and variants"}})
        mapper = RoleMapper("role_mapper/config/roles.yaml")
        
        search_queries = ["data analyst", "business intelligence", "data scientist"]
        for query in search_queries:
            role = mapper.find_role(query)
            if role:
                logger.info("role_found", extra={
                    "extra_data": {
                        "query": query,
                        "role_key": role.role_key,
                        "variants_count": len(role.variants),
                        "primary_names": role.primary_names,
                    }
                })
                
                # Find related roles
                related = mapper.get_related_roles(role.role_key, threshold=0.6)
                if related:
                    logger.info("related_roles_found", extra={
                        "extra_data": {
                            "query": query,
                            "related_count": len(related),
                            "top_3": [(r[0], f"{r[1]:.2f}") for r in related[:3]],
                        }
                    })
        
        # =================================================================
        # 5. EXPORT WITH LINEAGE
        # =================================================================
        logger.info("step_5_export_lineage", extra={"extra_data": {"action": "Exporting with lineage metadata"}})
        
        lineage = DatasetLineage(
            source_url="https://www.getonbrd.com/jobs",
            source_type="web_scrape_demo",
            extraction_method="getonboard_scraper_v2_demo",
            extraction_timestamp=datetime.utcnow().isoformat(),
            record_count=len(jobs),
            schema_version="JobV2",
            data_quality_metrics={
                "total_records": quality_report.metrics.total_records,
                "valid_records": quality_report.metrics.valid_records,
                "invalid_records": quality_report.metrics.invalid_records,
                "avg_confidence": quality_report.metrics.avg_confidence,
                "null_description_rate": quality_report.metrics.null_description_rate,
            },
            owner="data-engineering-demo@company.com"
        )
        
        output_file = export_jobs(jobs, role="data_engineer_demo", lineage=lineage)
        logger.info("jobs_exported", extra={"extra_data": {"output_file": output_file}})
        
        # =================================================================
        # 6. DISPLAY RESULTS
        # =================================================================
        logger.info("step_6_display_results", extra={"extra_data": {"action": "Displaying sample output"}})
        
        with open(output_file, "r") as f:
            exported_data = json.load(f)
        
        print("\n" + "="*70)
        print("📊 EXPORTED JSON STRUCTURE (Schema V2 with Lineage)")
        print("="*70)
        print(json.dumps(exported_data["_metadata"], indent=2))
        
        print("\n" + "="*70)
        print("📋 SAMPLE JOB RECORD (First record)")
        print("="*70)
        print(json.dumps(exported_data["data"][0], indent=2))
        
        print("\n" + "="*70)
        print("✅ DEMO SUMMARY")
        print("="*70)
        print(f"Total Jobs Processed: {len(jobs)}")
        print(f"Valid Records: {quality_report.metrics.valid_records}")
        print(f"Average Confidence: {quality_report.metrics.avg_confidence:.2%}")
        print(f"Output File: {output_file}")
        print(f"File Size: {Path(output_file).stat().st_size:,} bytes")
        
        logger.info("demo_completed_successfully", extra={
            "extra_data": {
                "total_jobs": len(jobs),
                "valid_records": quality_report.metrics.valid_records,
                "output_file": output_file,
            }
        })
        
        print("\n" + "="*70)
        print("🎉 ALL REFACTORING PATTERNS DEMONSTRATED:")
        print("="*70)
        print("✅ Structured JSON Logging")
        print("✅ Data Quality Framework with Confidence Scoring")
        print("✅ Checkpoint System (SQLite Idempotency)")
        print("✅ Schema Versioning (JobV2)")
        print("✅ Resilience Patterns (integrated in codebase)")
        print("✅ Role Mapper (Fuzzy Matching + Variants)")
        print("✅ Lineage & Audit Trail (in JSON export)")
        print("✅ Configuration Management (Pydantic Settings)")
        print("\n")
        
        checkpoint.close()
        
    except Exception as e:
        logger.error("demo_failed", extra={"extra_data": {"error": str(e)}}, exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
