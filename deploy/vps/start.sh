#!/usr/bin/env bash
# First start / update on the VPS. Run from the repo root: ./deploy/vps/start.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

[ -f .env ] || { echo "missing .env (cp .env.example .env and fill it in)"; exit 1; }
grep -q '^ADMIN_API_KEY=.\+' .env || echo "WARNING: ADMIN_API_KEY is empty (python -m app.cli secret)"

sudo mkdir -p /srv/devagent/data
sudo chown -R 1000:1000 /srv/devagent/data config

export DOCKER_GID="$(getent group docker | cut -d: -f3)"
echo ">> building sandbox image"
docker build -q -f Dockerfile.sandbox -t devagent-sandbox:latest .
echo ">> starting stack"
docker compose -f deploy/vps/docker-compose.yml up -d --build

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then
    echo ">> healthy: $(curl -fsS http://127.0.0.1:8080/health)"
    exit 0
  fi
  sleep 2
done
echo "app did not become healthy; check: docker compose -f deploy/vps/docker-compose.yml logs app"
exit 1
