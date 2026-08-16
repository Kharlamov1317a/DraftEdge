#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-8501}"
exec streamlit run app.py --server.address=0.0.0.0 --server.port="$PORT" --server.headless=true
