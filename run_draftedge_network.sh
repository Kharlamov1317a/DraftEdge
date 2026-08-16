#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

LAN_IP=""
if command -v ipconfig >/dev/null 2>&1; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
fi
if [ -z "$LAN_IP" ] && command -v hostname >/dev/null 2>&1; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi

printf '\nDraftEdge is starting.\n'
printf 'Computer: http://localhost:8501\n'
if [ -n "$LAN_IP" ]; then
  printf 'iPhone on the same Wi-Fi: http://%s:8501\n' "$LAN_IP"
else
  printf 'iPhone: use your computer LAN/IPv4 address as http://<LAN-IP>:8501\n'
fi
printf 'Keep this terminal and the computer awake while using LAN mode.\n\n'

exec streamlit run app.py --server.address=0.0.0.0 --server.port=8501
