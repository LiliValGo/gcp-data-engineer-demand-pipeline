"""
Entry point for the MCP Server.

Run with:
    python run_mcp.py

Test in the MCP Inspector (no Claude Desktop required):
    npx @modelcontextprotocol/inspector python run_mcp.py
    # Opens http://localhost:5173
"""

from mcp_server.server import mcp

if __name__ == "__main__":
    mcp.run()
