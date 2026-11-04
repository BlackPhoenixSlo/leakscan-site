#!/usr/bin/env bash
# Deploy this repo (landing site + scan API, one origin) to the VPS. Idempotent; re-run any time.
# Usage: deploy/push.sh <ssh-host>        e.g. deploy/push.sh root@72.62.92.114
# 1) tar backup of /root/leakscan code (not .env, not the data volume) -> /root/leakscan-backups/
# 2) rsync app/ site/ (--delete inside those two only) + deploy/{Dockerfile,docker-compose.yml} + .dockerignore
# 3) LEAKSCAN_PORT=8081 docker compose --env-file .env -p leakscan -f deploy/docker-compose.yml up -d --build
# 4) wait for the container healthcheck, then deploy/smoke.sh on the VPS (port 8081) and over https.
set -euo pipefail
H="${1:?usage: deploy/push.sh <ssh-host>}"
R=/root/leakscan
cd "$(dirname "$0")/.."
[ -f app/public_app.py ] && [ -f site/index.html ] || { echo "run from a leakscan-site checkout" >&2; exit 2; }

echo "== backup"
ssh "$H" "set -e; test -f $R/.env || { echo 'missing $R/.env' >&2; exit 3; }
  mkdir -p /root/leakscan-backups; cd $R
  f=/root/leakscan-backups/leakscan-\$(date -u +%Y%m%dT%H%M%SZ).tgz
  tar czf \$f \$(ls -d *.py public_static site app deploy docker-compose.yml Dockerfile .dockerignore 2>/dev/null)
  echo \"backup \$f\""

echo "== rsync"
ssh "$H" "mkdir -p $R/app $R/site $R/deploy"
RS=(rsync -az --exclude __pycache__/ --exclude '*.pyc' --exclude .DS_Store)
"${RS[@]}" --delete app/ "$H:$R/app/"
"${RS[@]}" --delete site/ "$H:$R/site/"
"${RS[@]}" deploy/Dockerfile deploy/docker-compose.yml "$H:$R/deploy/"
"${RS[@]}" .dockerignore "$H:$R/.dockerignore"

echo "== build + up"
ssh "$H" "cd $R && LEAKSCAN_PORT=8081 docker compose --env-file .env -p leakscan -f deploy/docker-compose.yml up -d --build"

echo "== wait healthy"
for _ in $(seq 1 30); do
  s="$(ssh "$H" "docker inspect -f '{{.State.Health.Status}}' leakscan-app" 2>/dev/null || true)"
  [ "$s" = healthy ] && break; sleep 3
done
echo "health: ${s:-unknown}"

# https hosts from the VPS .env (compose defaults when unset)
envv() { ssh "$H" "grep -E '^$1=' $R/.env | tail -1 | cut -d= -f2- | tr -d '\"\r'" || true; }
API_HOST="$(envv LEAKSCAN_HOST)"; API_HOST="${API_HOST:-scan.srv1395798.hstgr.cloud}"
SITE_HOST="$(envv SITE_HOST)"; SITE_HOST="${SITE_HOST:-abolita.srv1395798.hstgr.cloud}"

echo "== smoke (VPS :8081)"
ssh "$H" "bash -s -- http://127.0.0.1:8081" < deploy/smoke.sh
echo "== smoke (https: $API_HOST $SITE_HOST)"
bash deploy/smoke.sh "https://$API_HOST" "$API_HOST" "$SITE_HOST"
echo "deployed. rollback: tar xzf the backup above in $R, then the old root compose: cd $R && LEAKSCAN_PORT=8081 docker compose -p leakscan up -d --build"
