"""Controlled product and component vocabulary."""

from __future__ import annotations

import re


PRODUCT_ALIASES = {
    "rancher_manager": {
        "rancher",
        "rancher manager",
        "rancher management server",
        "rancher 管理器",
    },
    "kubernetes": {"kubernetes", "k8s"},
    "fleet": {"fleet", "rancher fleet", "舰队"},
    "rke": {"rke", "rancher kubernetes engine"},
    "rke2": {"rke2", "rke 2", "rancher kubernetes engine 2"},
    "eks": {"eks", "amazon eks", "elastic kubernetes service"},
    "helm": {"helm"},
    "docker": {"docker"},
}

COMPONENT_ALIASES = {
    "rancher_server": {"rancher server", "rancher-server"},
    "cluster_agent": {
        "cluster agent",
        "cluster-agent",
        "cattle cluster agent",
        "cattle-cluster-agent",
        "集群代理",
    },
    "fleet_agent": {"fleet agent", "fleet-agent"},
    "cattle_node_agent": {"cattle node agent", "cattle-node-agent", "node agent"},
    "api_server": {"api server", "api-server", "kube apiserver", "kube-apiserver"},
    "service_account": {"serviceaccount", "service account", "service-account", "服务账户"},
    "registration_token": {"registration token", "registration-token", "注册令牌"},
    "cloud_credential": {"cloud credential", "cloud-credential"},
    "secret": {"secret", "kubernetes secret"},
    "rbac": {
        "rbac",
        "role based access control",
        "role-based access control",
        "基于角色的访问控制",
    },
    "websocket": {"websocket", "web socket"},
    "reverse_tunnel": {"reverse tunnel", "reverse-tunnel", "反向隧道"},
    "cattle_impersonation_system": {
        "cattle impersonation system",
        "cattle-impersonation-system",
    },
    "bundle": {"bundle", "fleet bundle"},
    "rke": {"rke", "rancher kubernetes engine"},
    "rke2": {"rke2", "rke 2", "rancher kubernetes engine 2"},
    "cve": {"cve", "common vulnerabilities and exposures"},
}

OFFICIAL_SOURCE_PRIORITIES = {
    "services.nvd.nist.gov": 85,
    "documentation.suse.com": 100,
    "ranchermanager.docs.rancher.com": 100,
    "rancher.com": 100,
    "fleet.rancher.io": 95,
    "github.com": 95,
    "api.github.com": 95,
    "kubernetes.io": 90,
    "cve.org": 85,
    "nvd.nist.gov": 85,
    "helm.sh": 80,
    "docs.docker.com": 80,
}

NETWORK_EVIDENCE_DOMAINS = {
    "services.nvd.nist.gov",
    "nvd.nist.gov",
    "api.github.com",
    "github.com",
}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.lower()).strip()


def _lookup(value: str, aliases: dict[str, set[str]]) -> str:
    normalized = _normalize(value)
    for canonical, values in aliases.items():
        if normalized == _normalize(canonical) or normalized in {
            _normalize(alias) for alias in values
        }:
            return canonical
    raise ValueError(f"Unknown controlled vocabulary value: {value}")


def normalize_product(value: str) -> str:
    return _lookup(value, PRODUCT_ALIASES)


def normalize_component(value: str) -> str:
    return _lookup(value, COMPONENT_ALIASES)


def products_match(left: str, right: str) -> bool:
    try:
        return normalize_product(left) == normalize_product(right)
    except ValueError:
        return False


def components_match(left: str, right: str) -> bool:
    try:
        return normalize_component(left) == normalize_component(right)
    except ValueError:
        return False


def normalize_official_domain(value: str) -> str:
    domain = value.strip().lower().rstrip(".")
    if domain not in OFFICIAL_SOURCE_PRIORITIES:
        raise ValueError(f"Domain is not in the official evidence whitelist: {value}")
    return domain


def source_priority_for_domain(value: str) -> int:
    return OFFICIAL_SOURCE_PRIORITIES[normalize_official_domain(value)]


def is_allowed_network_domain(value: str) -> bool:
    return value.strip().lower().rstrip(".") in NETWORK_EVIDENCE_DOMAINS
