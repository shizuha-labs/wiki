#!/bin/bash
# Local mirror of ci-test-wiki: wiki.tests in the live image lineage.
# Uses a persistent PostgreSQL cache and the image's installed dependency set;
# the gate never performs network installs. Reset: docker volume rm wiki-gate-pgdata
set -euo pipefail
# Concurrent gate runs share the wiki-gate-pgdata volume: two postgres
# containers on one data dir corrupt it (then every later run wedges in crash
# recovery). flock queues concurrent pushes; 15min cap then fail loud.
exec 9>/tmp/wiki-gate.volume.lock
flock -w 900 9 || { echo "gate: another gate run held the lock >15min — investigate (docker ps | grep wiki-gate)" >&2; exit 1; }
cd "$(git rev-parse --show-toplevel)"
IMG="${SHIZUHA_CI_IMAGE:-}"
[ -z "$IMG" ] && command -v kubectl >/dev/null 2>&1 && IMG=$(kubectl get deploy -n shizuha shizuha-wiki -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)
IMG="${IMG:-localhost:30500/shizuha-wiki:wiki-2009dc3}"
NET="wiki-gate-$$"; PG="wiki-gate-pg-$$"; RD="wiki-gate-redis-$$"; TEST="wiki-gate-test-$$"
cleanup() { docker stop -t 20 "$PG" >/dev/null 2>&1 || true; docker rm -f "$TEST" "$PG" "$RD" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker volume create wiki-gate-pgdata >/dev/null
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -v wiki-gate-pgdata:/var/lib/postgresql/data -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=shizuha_wiki_ci postgres:16-alpine >/dev/null
docker run -d --name "$RD" --network "$NET" redis:7-alpine >/dev/null
wait_pg() {
  for _i in $(seq 1 90); do
    docker exec "$PG" psql -U postgres -h 127.0.0.1 -c "SELECT 1" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}
if ! wait_pg; then
  # Cached volume wedged (interrupted WAL recovery etc.) — it is only a cache:
  # recreate it fresh and retry once (next run repays migrations, then warm again).
  echo "gate: postgres not ready — recreating cache volume wiki-gate-pgdata and retrying" >&2
  docker rm -f "$PG" >/dev/null 2>&1
  docker volume rm wiki-gate-pgdata >/dev/null 2>&1
  docker volume create wiki-gate-pgdata >/dev/null
  docker run -d --name "$PG" --network "$NET" -v wiki-gate-pgdata:/var/lib/postgresql/data -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=shizuha_wiki_ci postgres:16-alpine >/dev/null
  wait_pg || { echo "gate: postgres STILL not ready — aborting" >&2; exit 1; }
fi
echo "gate: image=$IMG"
timeout 900 docker run --rm --name "$TEST" --network "$NET" --entrypoint sh \
  -v "$PWD/wiki":/app/wiki -v "$PWD/wikimanager":/app/wikimanager \
  -v "$PWD/.forgejo":/app/.forgejo:ro \
  -v "$PWD/.ci-local-gate.sh":/app/.ci-local-gate.sh:ro \
  -e POSTGRES_HOST="$PG" -e POSTGRES_PORT=5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=shizuha_wiki_ci \
  -e CELERY_BROKER_URL="redis://$RD:6379/5" -e CELERY_RESULT_BACKEND="redis://$RD:6379/5" \
  -e DEBUG=True -e SECRET_KEY=ci-secret -e JWT_SECRET_KEY=ci-secret \
  "$IMG" -c "python manage.py test wiki.tests --noinput --keepdb"
