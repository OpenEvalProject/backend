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

# Run database migration (add embedding columns if they don't exist)
echo "Running database migrations..."
"$UV" run python scripts/migrate_add_embeddings.py || echo "Migration failed or already applied"

# Ingest new manuscripts
echo "Ingesting manuscripts..."
"$UV" run python -m app.ingest_manuscripts \
  --manuscripts-dir "$EVALS_DIR/manuscripts" || echo "Ingestion failed or no new manuscripts"

# Generate embeddings for new claims (incremental - only embeds claims without embeddings)
echo "Generating embeddings for new claims..."
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  "$UV" run python scripts/embed_claims.py || echo "Embedding generation failed or no new claims"
else
  echo "WARNING: OPENAI_API_KEY not set. Skipping embedding generation."
  echo "Set OPENAI_API_KEY in /etc/environment or backend .env file to enable claim search."
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
