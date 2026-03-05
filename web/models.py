"""Pydantic models for API requests/responses"""

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class RoleSearchRequest(BaseModel):
    """Request body for role search"""
    query: str


class RoleInfo(BaseModel):
    """Response model for role information"""
    role_key: str
    primary_names: List[str]
    variants: List[str]
    description: str


class SearchResponse(BaseModel):
    """Response for role search"""
    query: str
    found: bool
    role: Optional[RoleInfo] = None


class VariantsResponse(BaseModel):
    """Response for variants listing"""
    role_key: str
    primary_names: List[str]
    variants: List[str]
    total_variants: int


class RelatedRole(BaseModel):
    """Related role with similarity score"""
    role_key: str
    similarity_score: float
    primary_names: List[str]


class RelatedRolesResponse(BaseModel):
    """Response for related roles"""
    role_key: str
    related: List[RelatedRole]


class ScraperRequest(BaseModel):
    """Request to trigger scraping"""
    role_key: str
    custom_search_terms: Optional[List[str]] = None


class ScraperResponse(BaseModel):
    """Response from scraper trigger"""
    status: str
    role: str
    job_id: str
    queued_at: datetime


class ScraperStatusResponse(BaseModel):
    """Response for scraper status"""
    job_id: str
    status: str  # queued, running, completed, failed
    progress: int  # 0-100
    records_processed: int
    completed_at: Optional[datetime] = None
