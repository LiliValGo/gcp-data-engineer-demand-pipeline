"""
Search strategy mapping for GetonBoard
Maps search terms to appropriate category URLs
"""

import logging
from typing import List

logger = logging.getLogger(__name__)

# URL mapping by GetonBoard category
CATEGORY_URLS = {
    "data-science-analytics": [
        "https://www.getonbrd.com/jobs/data-science-analytics",
        "https://www.getonbrd.com/empleos/data-science-analytics",
    ],
    "backend": [
        "https://www.getonbrd.com/jobs/backend",
        "https://www.getonbrd.com/empleos/backend",
    ],
    "frontend": [
        "https://www.getonbrd.com/jobs/frontend",
        "https://www.getonbrd.com/empleos/frontend",
    ],
}

# Legacy mapping for backward compatibility
SEARCH_STRATEGY_URLS = {
    "data engineer": {
        "urls": CATEGORY_URLS["data-science-analytics"],
        "keywords": ["data engineer"]
    },
    "ingeniero de datos": {
        "urls": CATEGORY_URLS["data-science-analytics"],
        "keywords": ["ingeniero", "datos"]
    },
    "analytics engineer": {
        "urls": CATEGORY_URLS["data-science-analytics"],
        "keywords": ["analytics", "engineer"]
    },
    "big data engineer": {
        "urls": CATEGORY_URLS["data-science-analytics"],
        "keywords": ["big data", "engineer"]
    },
    "etl developer": {
        "urls": CATEGORY_URLS["data-science-analytics"],
        "keywords": ["etl", "developer"]
    }
}


def get_strategy_urls(search_term: str) -> List[str]:
    """
    Get strategy URLs for a search term.

    First tries to get URLs from role_mapper, falls back to legacy mapping.

    Args:
        search_term: Job search term

    Returns:
        List of URLs to try
    """
    term_lower = search_term.lower()

    # Try role mapper first (if available)
    try:
        from role_mapper.role_mapper import RoleMapper
        mapper = RoleMapper("role_mapper/config/roles.yaml")
        role = mapper.find_role(term_lower)
        if role:
            category = role.category
            if category in CATEGORY_URLS:
                logger.debug(f"Strategy for '{search_term}': {category}")
                return CATEGORY_URLS[category]
    except Exception as e:
        logger.debug(f"Role mapper not available: {e}")

    # Fallback to legacy mapping
    if term_lower in SEARCH_STRATEGY_URLS:
        return SEARCH_STRATEGY_URLS[term_lower]["urls"]

    # Try keyword matching
    for strategy_key, strategy_data in SEARCH_STRATEGY_URLS.items():
        for keyword in strategy_data["keywords"]:
            if keyword.lower() in term_lower:
                logger.debug(f"Strategy for '{search_term}' (keyword match): {strategy_key}")
                return strategy_data["urls"]

    # Default to data-science-analytics
    logger.debug(f"Strategy for '{search_term}': default (data-science-analytics)")
    return CATEGORY_URLS["data-science-analytics"]

