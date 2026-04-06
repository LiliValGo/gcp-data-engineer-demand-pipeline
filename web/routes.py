"""API routes for role exploration and scraping"""

from fastapi import APIRouter, HTTPException, Request
from typing import List, Dict, Optional
import logging

router = APIRouter(prefix="/api", tags=["roles"])

logger = logging.getLogger(__name__)


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


@router.get("/search")
async def search_role(query: str, request: Request):
    """Search for a role by name and return its variants and related roles"""
    logger.info(f"Searching for role: {query}")
    role_mapper = _get_role_mapper(request)

    role = role_mapper.find_role(query)
    if not role:
        return {"query": query, "found": False, "results": []}

    related = role_mapper.get_related_roles(query)

    return {
        "query": query,
        "found": True,
        "results": [
            {
                "role_key": role.role_key,
                "primary_names": role.primary_names,
                "variants": role.variants,
                "category": role.category,
                "related_roles": [
                    {"role_key": rk, "score": round(score, 2)}
                    for rk, score in related
                ],
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


@router.post("/scrape")
async def scrape_role(role_key: str):
    """[Pending Phase 3] Trigger background scraping for a given role"""
    logger.info(f"Scraping triggered for: {role_key}")
    # Implemented in Phase 3 alongside DuckDB and orchestration
    return {
        "status": "not_implemented",
        "detail": "Scraping via API is implemented in Phase 3 of the roadmap",
        "role": role_key,
    }


@router.get("/status/{job_id}")
async def get_scrape_status(job_id: str):
    """[Pending Phase 3] Get status of a scraping job"""
    return {
        "job_id": job_id,
        "status": "not_implemented",
        "detail": "Status tracking is implemented in Phase 3 of the roadmap",
    }
