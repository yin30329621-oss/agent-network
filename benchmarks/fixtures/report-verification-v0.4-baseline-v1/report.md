# Rancher Report Verification Baseline

## Architecture

Cluster Agent establishes a reverse tunnel to Rancher Server for downstream cluster management.

Rancher Server communicates with the downstream cluster through the Cluster Agent connection.

Cluster Agent always uses WebSocket for every Rancher Server connection.

## Authorization

Cluster Agent uses a ServiceAccount to access downstream Kubernetes resources.

RBAC roles and bindings grant the Cluster Agent ServiceAccount permissions to access Kubernetes resources.

## Registration

A registration token authenticates a new downstream cluster during registration.

## Transport Security

HTTPS and TLS protect communication between Cluster Agent and Rancher Server.

## Fleet Delivery

Fleet Agent applies Fleet Bundle resources to selected target clusters.

A Fleet Bundle describes GitOps resources for delivery to target clusters.

## Fleet Boundary

Rancher Manager Cluster Agent architecture is required for every Fleet Bundle workflow.

Fleet Bundle resources are distributed by the Rancher Manager Cluster Agent.

## Authorization Details

cattle-impersonation-system supports impersonation requests in Rancher Manager.

Cloud Credential stores cloud provider access configuration.

## Release Notes

Rancher Manager v2.14 release notes list changes for that release.

## Security Advisory

CVE-2025-1234 affects Rancher Manager v2.10.3.

## Version Comparison

Rancher Manager v2.13 uses the same Cluster Agent tunnel behavior as the cached v2.14 page.

## Citation Audit

Rancher Manager uses a Kubernetes ServiceAccount for RBAC access.

## Extraction Failure

The report extraction failed before this claim could be verified.

## Unavailable Evidence

The requested official document is unavailable in the local evidence cache.
