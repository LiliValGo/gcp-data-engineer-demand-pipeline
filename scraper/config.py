from dataclasses import dataclass
from typing import List


@dataclass
class ScraperConfig:
    base_url: str = "https://www.getonbrd.com/jobs"
    search_terms: List[str] = (
        "data engineer",
        "ingeniero de datos",
        "analytics engineer",
        "big data engineer",
        "etl developer",
    )
    timeout: int = 10
    max_retries: int = 3
    delay_between_requests: float = 1.5
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )


config = ScraperConfig()