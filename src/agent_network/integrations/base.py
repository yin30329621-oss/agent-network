"""Future integration interfaces."""

from __future__ import annotations

from typing import Protocol


class IntegrationPort(Protocol):
    """Base interface for future external integrations."""

    name: str

    def healthcheck(self) -> bool:
        """Return whether the integration is reachable."""
