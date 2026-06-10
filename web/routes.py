"""API routes for role exploration and scraping"""

from typing import List
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
import logging

router = APIRouter(prefix="/api", tags=["roles"])

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def _get_role_mapper(request: Request):
    """
    Dependency helper: retrieves the RoleMapper from app.state.

    Why app.state instead of a global variable?
    - Avoids circular imports (routes imports app, app imports routes)
    - The object is initialized once when the server starts
    - Testable: in tests we can inject a mock into app.state
    """
    role_mapper = request.app.state.role_mapper
    if role_mapper is None:
        raise HTTPException(status_code=503, detail="RoleMapper not available")
    return role_mapper


# ---------------------------------------------------------------------------
# Role exploration endpoints
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_role(query: str, request: Request):
    """
    Search for a role by free text and return its keyword variants.

    For roles known in roles.yaml, the full variant list is returned.
    For unknown roles, Gemini API generates intelligent variants (or falls
    back to templates if Gemini is unavailable).
    """
    logger.info(f"Searching for role: {query}")
    role_mapper = _get_role_mapper(request)

    role = role_mapper.find_role(query)
    if role:
        # Role found in YAML catalog
        variants = role.variants
        related = [
            {"role_key": rk, "score": round(score, 2)}
            for rk, score in role_mapper.get_related_roles(query)
        ]
        role_key = role.role_key
        source = "catalog"
    else:
        # Unknown role: generate with Gemini or fallback to templates
        role_data = role_mapper.generate_variants_with_gemini(query)
        if role_data:
            variants = role_data["variants"]
            related = []
            role_key = role_data["role_key"]
            source = "gemini_generated" if role_mapper.gemini_model else "template_generated"
        else:
            return {
                "query": query,
                "found": False,
                "results": [],
                "error": "Could not generate variants for this role",
            }

    return {
        "query": query,
        "found": role is not None,
        "source": source,
        "results": [
            {
                "role_key": role_key,
                "variants": variants,
                "related_roles": related,
            }
        ],
    }


@router.get("/variants/{role_key}")
async def get_variants(role_key: str, request: Request):
    """Return all variants of a role by its key"""
    logger.info(f"Getting variants for: {role_key}")
    role_mapper = _get_role_mapper(request)

    variants = role_mapper.get_all_variants(role_key)
    if variants is None:
        raise HTTPException(status_code=404, detail=f"Role '{role_key}' not found")

    return {"role_key": role_key, "variants": variants, "total": len(variants)}


@router.get("/related/{role_key}")
async def get_related_roles(role_key: str, request: Request, threshold: float = 0.6):
    """Return roles related to a given role, sorted by similarity score"""
    logger.info(f"Getting related roles for: {role_key}")
    role_mapper = _get_role_mapper(request)

    related = role_mapper.get_related_roles(role_key, threshold=threshold)

    return {
        "role_key": role_key,
        "threshold": threshold,
        "related": [
            {"role_key": rk, "score": round(score, 2)} for rk, score in related
        ],
    }


@router.get("/roles")
async def list_all_roles(request: Request):
    """List all available roles with their names and variants"""
    role_mapper = _get_role_mapper(request)

    roles = role_mapper.list_all_roles()
    return {"total": len(roles), "roles": roles}


# ---------------------------------------------------------------------------
# Scraping endpoints
# ---------------------------------------------------------------------------

class ScrapeRequest(BaseModel):
    """Body for POST /api/scrape"""
    role_key: str
    variants: List[str]


def _run_scrape(job_id: str, role_key: str, variants: List[str], jobs: dict) -> None:
    """
    Background function executed by FastAPI BackgroundTasks.

    Runs Selenium scraping for each variant term, exports to Bronze,
    and refreshes the Silver/Gold Medallion layers. Updates jobs[job_id]
    with progress so the frontend can poll /api/status/{job_id}.

    Why lazy imports inside the function?
    The scraper imports are heavy (Selenium, pandas, DuckDB). Keeping them
    here avoids loading them at web-server startup when no scraping is needed.
    """
    from datetime import datetime

    from scraper.client import GetOnBoardClient
    from scraper.exporter import DatasetLineage, export_jobs
    from scraper.medallion import MedallionPipeline
    from scraper.parser import parse_jobs

    client = None
    try:
        client = GetOnBoardClient()
        all_jobs = []

        for i, term in enumerate(variants):
            try:
                html = client.search(term)
                found = parse_jobs(html, term)
                all_jobs.extend(found)
                logger.info(f"[scrape:{job_id}] '{term}' → {len(found)} jobs")
            except Exception as e:
                logger.warning(f"[scrape:{job_id}] '{term}' failed: {e}")
            finally:
                jobs[job_id]["progress"] = i + 1

        # Bronze export + Medallion pipeline (Silver → Gold)
        if all_jobs:
            lineage = DatasetLineage(
                source_url="https://www.getonbrd.com/jobs",
                source_type="web_scrape",
                extraction_method="getonboard_scraper_v2",
                extraction_timestamp=datetime.utcnow().isoformat(),
                record_count=len(all_jobs),
                schema_version="JobV2",
                data_quality_metrics={},
                owner="data-engineering@company.com",
            )
            bronze_file = export_jobs(all_jobs, role=role_key, lineage=lineage)
            pipeline = MedallionPipeline()
            pipeline.run_full_pipeline()
            pipeline.close()
            jobs[job_id]["result"] = {
                "jobs_found": len(all_jobs),
                "bronze_file": bronze_file,
            }
        else:
            jobs[job_id]["result"] = {"jobs_found": 0, "bronze_file": None}

        jobs[job_id]["status"] = "done"

    except Exception as e:
        logger.error(f"[scrape:{job_id}] Fatal error: {e}", exc_info=True)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
    finally:
        if client:
            client.close()


@router.post("/scrape")
async def scrape_role(
    request: Request,
    body: ScrapeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger background scraping for a role and its keyword variants.

    Returns a job_id immediately. Poll GET /api/status/{job_id} to track
    progress. Only one scrape can run at a time (returns 409 if one is
    already in progress).
    """
    jobs = request.app.state.scrape_jobs

    if any(j["status"] == "running" for j in jobs.values()):
        raise HTTPException(
            status_code=409,
            detail="Un scraping ya está en progreso. Espera a que termine.",
        )

    job_id = str(uuid4())
    jobs[job_id] = {
        "status": "running",
        "variants": body.variants,
        "progress": 0,
        "total": len(body.variants),
        "result": None,
        "error": None,
    }
    background_tasks.add_task(_run_scrape, job_id, body.role_key, body.variants, jobs)
    return {"job_id": job_id, "status": "running", "total_variants": len(body.variants), "total": len(body.variants)}


@router.get("/status/{job_id}")
async def get_scrape_status(job_id: str, request: Request):
    """Get the current status and progress of a scraping job."""
    jobs = request.app.state.scrape_jobs
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {"job_id": job_id, **jobs[job_id]}
