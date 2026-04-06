"""FastAPI application for Job Market Role Explorer"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import logging

from role_mapper.role_mapper import RoleMapper
from web.routes import router

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Job Market Role Explorer",
    description="Explore job roles and scrape market data",
    version="1.0.0"
)

# Initialize role mapper and store it in app.state so routes can access it
# via dependency injection (Request.app.state.role_mapper)
try:
    app.state.role_mapper = RoleMapper("role_mapper/config/roles.yaml")
except Exception as e:
    logger.error(f"Failed to initialize role mapper: {e}")
    app.state.role_mapper = None

# Register the API router
app.include_router(router)

# Mount static files
try:
    app.mount("/static", StaticFiles(directory="web/static"), name="static")
except Exception as e:
    logger.warning(f"Could not mount static files: {e}")


@app.get("/")
async def root():
    """Serve the main page"""
    return FileResponse("web/templates/index.html", media_type="text/html")


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "service": "job-role-explorer"}
