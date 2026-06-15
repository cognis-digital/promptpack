"""PROMPTPACK MCP server — exposes the prompt registry as an MCP tool for Cognis.Studio."""
from __future__ import annotations

import json

from promptpack.core import Registry, DEFAULT_DB, PromptPackError


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
    def promptpack_list(db: str = DEFAULT_DB) -> str:
        """List all prompts in the registry. Returns JSON."""
        try:
            reg = Registry(db)
            return json.dumps(reg.list_prompts(), indent=2)
        except PromptPackError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool()
    def promptpack_get(name: str, ref: str = "", db: str = DEFAULT_DB) -> str:
        """Get a prompt version by name and optional ref. Returns JSON."""
        try:
            reg = Registry(db)
            obj = reg.get(name, ref or None)
            return json.dumps(obj, indent=2)
        except PromptPackError as exc:
            return json.dumps({"error": str(exc)})

    app.run()
    return 0
