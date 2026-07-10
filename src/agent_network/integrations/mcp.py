"""Reserved MCP integration boundary."""

from dataclasses import dataclass


@dataclass(slots=True)
class MCPIntegration:
    name: str = "mcp"

    def healthcheck(self) -> bool:
        return False
