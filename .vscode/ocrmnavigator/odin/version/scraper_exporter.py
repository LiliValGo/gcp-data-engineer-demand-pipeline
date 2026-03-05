import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import asdict, dataclass

from .models import Job

logger = logging.getLogger(__name__)


@dataclass
class DatasetLineage:
    """Metadata for data provenance and audit trail"""
    source_url: str
    source_type: str
    extraction_method: str
    extraction_timestamp: str
    record_count: int
    schema_version: str
    data_quality_metrics: Dict[str, Any]
    owner: Optional[str] = None


def export_jobs(
    jobs: List[Job],
    role: str = "data_engineer",
    lineage: Optional[DatasetLineage] = None
) -> str:
    """
    Export jobs to JSON with schema versioning and lineage metadata
    
    Args:
        jobs: List of Job objects
        role: Role name for partitioning
        lineage: Optional lineage metadata
    
    Returns:
        Path to exported file
    """
    base_dir = Path("data/raw") / f"role={role}"
    base_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    file_path = base_dir / f"{today}__v2.json"

    # Create default lineage if not provided
    if not lineage:
        lineage = DatasetLineage(
            source_url="https://www.getonbrd.com/jobs",
            source_type="web_scrape",
            extraction_method="getonboard_scraper_v2",
            extraction_timestamp=datetime.utcnow().isoformat(),
            record_count=len(jobs),
            schema_version="JobV2",
            data_quality_metrics={
                "total_records": len(jobs),
                "records_with_description": len([j for j in jobs if j.description]),
                "records_with_skills": len([j for j in jobs if j.skills]),
                "avg_confidence": sum(j.description_confidence or 0.0 for j in jobs) / max(len(jobs), 1),
            },
            owner="data-engineering@company.com"
        )

    # Serialize data
    data = [job.model_dump(mode='json') for job in jobs]

    # Create metadata
    metadata = {
        "_metadata": {
            "schema_version": 2,
            "export_timestamp": datetime.utcnow().isoformat(),
            "total_records": len(jobs),
            "role": role,
            "lineage": asdict(lineage),
        },
        "data": data
    }

    # Save to file
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        file_size = file_path.stat().st_size
        logger.info(
            "jobs_exported",
            extra={
                "extra_data": {
                    "path": str(file_path),
                    "count": len(jobs),
                    "size_bytes": file_size
                }
            }
        )
        return str(file_path)
    
    except Exception as e:
        logger.error(f"Failed to export jobs: {e}", exc_info=True)
        raise
