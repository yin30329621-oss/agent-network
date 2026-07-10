"""Reserved GitHub integration boundary."""

from dataclasses import dataclass


@dataclass(slots=True)
class GitHubIntegration:
    name: str = "github"

    def healthcheck(self) -> bool:
        return False
