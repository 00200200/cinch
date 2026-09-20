#!/usr/bin/env bash
set -euo pipefail

echo "==> Validating Docker image sanity..."
docker build --check .
echo "==> Validation passed."
