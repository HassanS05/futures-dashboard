#!/usr/bin/env bash
# =====================================================================
# HR5 Invest — VPS deploy helper.
# Run this ON your VPS (e.g. 62.171.155.9) after installing Docker.
# =====================================================================
set -euo pipefail

cd "$(dirname "$0")"

echo "▶ HR5 Invest deploy"

if ! command -v docker >/dev/null 2>&1; then
  echo "✗ Docker is not installed. Install it first:"
  echo "    curl -fsSL https://get.docker.com | sh"
  exit 1
fi

if [ ! -f backend/.env ]; then
  echo "→ Creating backend/.env from template (edit it to add your keys)…"
  cp backend/.env.example backend/.env
  echo "  ⚠ Add FMP_API_KEY (live market data) and at least one AI key, then re-run."
fi

echo "→ Building & starting containers…"
docker compose up -d --build

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "✓ HR5 Invest is up:"
echo "    Frontend : http://${IP:-<vps-ip>}:3000"
echo "    API docs : http://${IP:-<vps-ip>}:8000/docs"
echo ""
echo "  Tip: for live quotes & AI, ensure backend/.env has your keys, then:"
echo "    docker compose up -d --build"
