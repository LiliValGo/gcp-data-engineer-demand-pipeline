import json
from pathlib import Path
from typing import List
from models import Job


def export_jobs(jobs: List[Job], filename: str):
    Path("output").mkdir(exist_ok=True)

    with open(f"output/{filename}", "w", encoding="utf-8") as f:
        json.dump(
            [job.model_dump() for job in jobs],
            f,
            indent=2,
            default=str
        )