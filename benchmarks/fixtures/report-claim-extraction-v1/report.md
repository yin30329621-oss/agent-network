# Architecture

Cluster Agent connects to Rancher Server through a reverse tunnel.

Overview

- ServiceAccount requires RBAC permissions to access Kubernetes resources.
- https://ranchermanager.docs.rancher.com/architecture
- Cluster Agent connects to Rancher Server through a reverse tunnel.

    kubectl get pods

Additional notes

~~~yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: example
~~~

## Transport Security

| Topic | Statement |
| --- | --- |
| TLS | HTTPS protects communication between Cluster Agent and Rancher Server. |
| Note | See https://ranchermanager.docs.rancher.com/security |

> Cluster Agent connects to Rancher Server through a reverse tunnel.
