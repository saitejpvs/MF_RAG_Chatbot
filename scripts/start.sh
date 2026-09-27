#!/usr/bin/env bash
# Render (and any PaaS) start command.
#
# The vector store and the MiniLM model are not in the repo: they are built at
# runtime. On an ephemeral filesystem that store is gone after every restart, so
# build it first, then serve. Ingest is idempotent, so this is safe either way.
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8501}"

if [ ! -d data/chroma ] || [ -z "$(ls -A data/chroma 2>/dev/null)" ]; then
  echo "[start] vector store missing, running ingest (5 sources -> 24 chunks)..."
  python -m ingest.run
else
  echo "[start] vector store already present, skipping ingest"
fi

echo "[start] serving Streamlit on 0.0.0.0:${PORT}"
exec streamlit run app/ui/app.py \
  --server.address 0.0.0.0 \
  --server.port "${PORT}" \
  --server.headless true \
  --browser.gatherUsageStats false
