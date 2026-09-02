#!/usr/bin/env sh
# Connect ilm_shamela's front proxy (search_caddy) to this stack's app containers
# over a dedicated edge network, WITHOUT exposing the generic `backend`/`frontend`
# service aliases to it (manual `docker network connect` adds only the container
# name as a resolvable alias). Idempotent — safe to re-run after any redeploy that
# recreates the app containers.
set -eu

EDGE=shaarawy_edge
PROXY=search_caddy
APPS="shaarawy_prod_backend shaarawy_prod_frontend"

docker network inspect "$EDGE" >/dev/null 2>&1 || docker network create "$EDGE" >/dev/null

connect() { # net container
  if docker inspect "$2" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null | tr ' ' '\n' | grep -qx "$1"; then
    echo "  $2 already on $1"
  else
    docker network connect "$1" "$2"
    echo "  connected $2 -> $1"
  fi
}

echo "Wiring $EDGE:"
connect "$EDGE" "$PROXY"
for a in $APPS; do connect "$EDGE" "$a"; done
