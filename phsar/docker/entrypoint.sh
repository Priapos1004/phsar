#!/usr/bin/env bash
set -euo pipefail

# Apply any pending Alembic migrations before starting the app.
# Fail fast on migration errors — serving traffic against an outdated
# schema is worse than a failed deploy.
echo "Running alembic upgrade head..."
alembic upgrade head

exec "$@"
