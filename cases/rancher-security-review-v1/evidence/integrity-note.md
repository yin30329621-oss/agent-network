# Evidence Integrity Note

The vendored raw evidence preserves upstream document and source contents as collected. Official Rancher and Kubernetes documentation/source files were not formatted or otherwise modified. Known trailing-whitespace and blank-line-at-EOF warnings reported by git diff --cached --check originate in upstream raw content and are intentionally retained for provenance. The extraction and chunk layers are the validation/indexing layers; they do not rewrite the raw evidence.
