"""
Minimal MCP server scaffold exposing Finam tools via JSON-RPC-like interface.
This is a placeholder to align with ARCHITECTURE.md; implementation will follow.
"""

from __future__ import annotations

from typing import Any, Dict


class MCPServer:
    def __init__(self) -> None:
        self.tools: Dict[str, Any] = {}

    def register_tool(self, name: str, func: Any) -> None:
        self.tools[name] = func

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in self.tools:
            raise KeyError(f"Tool not found: {name}")
        return self.tools[name](**kwargs)


def run() -> None:
    # Placeholder run entrypoint
    server = MCPServer()
    # Tools will be registered from src/mcp/tools/* modules in future edits
    print("Finam MCP server scaffold initialized (no tools registered yet)")


if __name__ == "__main__":
    run()



