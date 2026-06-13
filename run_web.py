#!/usr/bin/env python
"""Run the FastAPI web application"""

import uvicorn
from scraper.config import settings
from scraper.logging_config import setup_logging
from web.app import app

# Setup logging
logger = setup_logging(
    level=settings.log_level,
    log_format=settings.log_format
)

if __name__ == "__main__":
    logger.info(f"Starting Job Market Role Explorer")
    logger.info(f"Server: http://{settings.fastapi_host}:{settings.fastapi_port}")

    # When reload=True, must pass app as import string, not object
    app_str = "web.app:app" if settings.fastapi_reload else app

    uvicorn.run(
        app_str,
        host=settings.fastapi_host,
        port=settings.fastapi_port,
        reload=settings.fastapi_reload,
        log_level=settings.log_level.lower()
    )

