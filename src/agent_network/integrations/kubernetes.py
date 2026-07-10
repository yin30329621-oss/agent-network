"""Reserved Kubernetes integration boundary."""

from dataclasses import dataclass


@dataclass(slots=True)
class KubernetesIntegration:
    name: str = "kubernetes"

    def healthcheck(self) -> bool:
        return False
