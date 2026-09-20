---
name: docker-deploy
description: Docker deployment validation and container sanity checks
---

# Docker Deployment Helper

Before pushing containers to production registries:

1. Validate the Dockerfile build stages for multi-stage caching.
2. Run `./scripts/verify.sh` to confirm the container boots on non-root user.
3. Check that minimal base images (Alpine or distroless) are utilized.
