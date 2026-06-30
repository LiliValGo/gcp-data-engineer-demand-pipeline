import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from dataclasses import asdict, dataclass

import pandas as pd

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
    Export jobs to Parquet with lineage metadata

    Args:
        jobs: List of Job objects
        role: Role name for partitioning (Hive-style)
        lineage: Optional lineage metadata

    Returns:
        Path to exported parquet file
    """
    from .config import settings

    # Timestamped filename for immutability - each run creates a new file
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    if settings.gcs_bucket:
        parquet_file = f"gs://{settings.gcs_bucket}/bronze/role={role}/{timestamp}__v2.parquet"
        metadata_file = f"gs://{settings.gcs_bucket}/bronze/role={role}/{timestamp}__v2.metadata.json"
    else:
        base_dir = Path("data/bronze") / f"role={role}"
        base_dir.mkdir(parents=True, exist_ok=True)
        parquet_file = str(base_dir / f"{timestamp}__v2.parquet")
        metadata_file = str(base_dir / f"{timestamp}__v2.metadata.json")

    # Create default lineage if not provided
    if not lineage:
        lineage = DatasetLineage(
            source_url="https://www.getonbrd.com/jobs",
            source_type="web_scrape",
            extraction_method="getonboard_scraper_v2",
            extraction_timestamp=datetime.now(timezone.utc).isoformat(),
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

    # Serialize jobs to list of dicts
    data = [job.model_dump(mode='json') for job in jobs]

    # Convert to DataFrame
    df = pd.DataFrame(data)

    # Save parquet file
    try:
        df.to_parquet(
            parquet_file,
            engine='pyarrow',
            compression='snappy',
            index=False
        )

        # Save companion metadata file
        metadata = {
            "_metadata": {
                "schema_version": 2,
                "export_timestamp": datetime.now(timezone.utc).isoformat(),
                "total_records": len(jobs),
                "role": role,
                "lineage": asdict(lineage),
            }
        }

        if settings.gcs_bucket:
            import gcsfs
            fs = gcsfs.GCSFileSystem()
            with fs.open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            file_size = fs.info(parquet_file)["size"]
        else:
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            file_size = Path(parquet_file).stat().st_size

        logger.info(
            "jobs_exported",
            extra={
                "extra_data": {
                    "parquet_path": parquet_file,
                    "metadata_path": metadata_file,
                    "count": len(jobs),
                    "size_bytes": file_size
                }
            }
        )
        return parquet_file

    except Exception as e:
        logger.error(f"Failed to export jobs: {e}", exc_info=True)
        raise
