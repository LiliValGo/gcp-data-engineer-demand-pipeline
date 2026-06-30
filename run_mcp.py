"""
Entry point for the MCP Server.

Run with:
    python run_mcp.py

Test in the MCP Inspector (no Claude Desktop required):
    DANGEROUSLY_OMIT_AUTH=true npx @modelcontextprotocol/inspector \\
      ./venv/bin/python run_mcp.py
    # Opens http://localhost:6274

IMPORTANT — stdout is reserved for the MCP stdio protocol.
All application logs are redirected to stderr so they don't corrupt
the JSON-RPC frames that FastMCP writes to stdout.
"""

import logging
import sys

# Redirect ALL handlers to stderr before any import that might log to stdout.
# logging_config.py uses StreamHandler(sys.stdout) by default; we override that
# here so the MCP protocol channel (stdout) stays clean.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.WARNING,
    format="[%(levelname)s] %(name)s: %(message)s",
)

# Also silence the 'scraper' logger that logging_config.py may register
# on stdout when MedallionPipeline is imported.
for handler in logging.getLogger("scraper").handlers[:]:
    logging.getLogger("scraper").removeHandler(handler)
logging.getLogger("scraper").addHandler(logging.StreamHandler(sys.stderr))

from mcp_server.server import mcp  # noqa: E402 — import after logging setup

import os

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        port = int(os.getenv("PORT", "8080"))
        logger.warning(f"Starting MCP server on SSE transport on port {port}...")
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        mcp.run(transport="stdio")
