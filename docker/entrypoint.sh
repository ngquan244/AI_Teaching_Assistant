#!/bin/bash
set -e

# Run Alembic migrations only if RUN_MIGRATIONS is set to "true"
if [ "${RUN_MIGRATIONS}" = "true" ]; then
  echo "[entrypoint] Running Alembic migrations..."
  alembic upgrade head
  echo "[entrypoint] Migrations complete."
fi

# Execute the CMD passed to the container
exec "$@"
