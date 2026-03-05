#!/usr/bin/env python
"""Run the FastAPI web application"""

import uvicorn
import logging
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

    uvicorn.run(
        app,
        host=settings.fastapi_host,
        port=settings.fastapi_port,
        reload=settings.fastapi_reload,
        log_level=settings.log_level.lower()
    )

