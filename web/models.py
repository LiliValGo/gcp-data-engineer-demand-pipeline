"""Pydantic models for API requests/responses"""

from pydantic import BaseModel
from typing import List, Optional


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

