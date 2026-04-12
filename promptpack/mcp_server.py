"""PROMPTPACK MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from promptpack.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-promptpack[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-promptpack[mcp]'")
        return 1
    app = FastMCP("promptpack")

    @app.tool()
    def promptpack_scan(target: str) -> str:
        """Versioned prompt / template registry with A/B and rollbacks. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
