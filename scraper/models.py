from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import Optional, List


class Job(BaseModel):
    title: str
    company: str
    location: Optional[str]
    salary: Optional[str]
    url: HttpUrl
    description: Optional[str]
    search_term: str
    scraped_at: datetime