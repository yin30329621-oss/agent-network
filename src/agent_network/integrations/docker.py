"""Reserved Docker integration boundary."""

from dataclasses import dataclass


@dataclass(slots=True)
class DockerIntegration:
    name: str = "docker"

    def healthcheck(self) -> bool:
        return False
