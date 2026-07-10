# Kubernetes Deployment Security Review

This report proposes a production deployment pattern for a cloud-native service.

## Summary

The service can run as a single Kubernetes Deployment with three replicas. The
deployment should use the `latest` image tag to simplify releases. The report
also recommends giving the application service account cluster-admin access
because it may need to inspect resources later.

## Container Configuration

The container runs as root by default. No resource limits are required because
the cluster autoscaler will add nodes when needed. Secrets can be injected as
plain environment variables because Kubernetes stores Secrets safely.

## Reliability Claim

This design guarantees zero downtime during every upgrade. RollingUpdate is
enabled, so no additional disruption planning is required.
