#!/usr/bin/env bash
set -euo pipefail

FRONTEND_DIR=/var/www/html/openevalproject.com/public_html
BACKEND_DIR=/var/www/html/openevalproject.com/backend
EVALS_DIR=/var/www/html/openevalproject.com/evals
UV=/home/joules/.local/bin/uv

echo "=== Deploying OpenEvalProject ==="

# Pull frontend
echo "Pulling frontend..."
cd "$FRONTEND_DIR" && git pull --ff-only

# Pull backend
echo "Pulling backend..."
cd "$BACKEND_DIR" && git pull --ff-only

# Pull evals (if you want auto-updates)
echo "Pulling evals..."
cd "$EVALS_DIR" && git pull --ff-only || echo "Evals pull failed or not a git repo"

# Update backend dependencies
echo "Syncing backend dependencies..."
cd "$BACKEND_DIR"
[[ -d "$BACKEND_DIR/.venv" ]] || "$UV" venv
"$UV" sync

# Initialize or update database
DB_PATH="$BACKEND_DIR/claim_verification.db"
if [[ ! -f "$DB_PATH" ]]; then
  echo "Database not found. Creating new database from schema..."
  "$UV" run python -m app.db_init

  echo "Loading manuscripts from evals directory..."
  "$UV" run python load_cllm_data.py "$DB_PATH" "$EVALS_DIR/manuscripts"
else
  echo "Database exists. Updating with new data from evals..."
  "$UV" run python load_cllm_data.py "$DB_PATH" "$EVALS_DIR/manuscripts"
fi

# Restart backend service
echo "Restarting backend service..."
sudo -n systemctl restart openeval-backend

# Check service status
sudo -n systemctl status openeval-backend --no-pager || true

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Summary:"
echo "  - Frontend: $FRONTEND_DIR"
echo "  - Backend:  $BACKEND_DIR"
echo "  - Evals:    $EVALS_DIR"
echo ""
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "NOTE: Claim search will not work until OPENAI_API_KEY is configured."
fi
