#!/usr/bin/env bash
# Local Postgres and Redis for development, without Docker. Data lives in .data/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/.data"
PG_PORT="${PG_PORT:-5506}"
REDIS_PORT="${REDIS_PORT:-6406}"
PGDATA="$DATA/postgres"
PG_MIN_MAJOR=16

# Homebrew can leave several Postgres versions on PATH, some of them broken. PG_BIN pins
# one explicitly; otherwise the first working server of a supported version wins.
find_pg_bin() {
  local candidates=()
  [[ -n "${PG_BIN:-}" ]] && candidates+=("$PG_BIN")
  local on_path
  on_path="$(command -v postgres 2>/dev/null || true)"
  [[ -n "$on_path" ]] && candidates+=("$(dirname "$on_path")")
  for dir in /opt/homebrew/opt/postgresql@*/bin /usr/local/opt/postgresql@*/bin /usr/lib/postgresql/*/bin; do
    [[ -d "$dir" ]] && candidates+=("$dir")
  done
  for dir in "${candidates[@]}"; do
    local version major
    version="$("$dir/postgres" -V 2>/dev/null)" || continue
    major="$(sed -E 's/[^0-9]*([0-9]+).*/\1/' <<<"$version")"
    if (( major >= PG_MIN_MAJOR )); then
      if [[ -f "$PGDATA/PG_VERSION" && "$(cat "$PGDATA/PG_VERSION")" != "$major" ]]; then
        continue
      fi
      echo "$dir"
      return 0
    fi
  done
  echo "no usable PostgreSQL >= $PG_MIN_MAJOR found." >&2
  if [[ -f "$PGDATA/PG_VERSION" ]]; then
    echo "the data dir $PGDATA was created by PostgreSQL $(cat "$PGDATA/PG_VERSION")." >&2
  fi
  echo "set PG_BIN to its bin directory, e.g. PG_BIN=/opt/homebrew/opt/postgresql@17/bin" >&2
  return 1
}

pg_up() {
  local bin
  bin="$(find_pg_bin)"
  if [[ ! -f "$PGDATA/PG_VERSION" ]]; then
    mkdir -p "$DATA"
    "$bin/initdb" -D "$PGDATA" -U warden --auth=trust --encoding=UTF8 >/dev/null
  fi
  if ! "$bin/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
    "$bin/pg_ctl" -D "$PGDATA" -l "$DATA/postgres.log" -w \
      -o "-p $PG_PORT -k /tmp -c listen_addresses=127.0.0.1" start >/dev/null
  fi
  for db in warden warden_test warden_demo_test; do
    "$bin/psql" -h 127.0.0.1 -p "$PG_PORT" -U warden -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 ||
      "$bin/createdb" -h 127.0.0.1 -p "$PG_PORT" -U warden "$db"
  done
  echo "postgres  127.0.0.1:$PG_PORT ($("$bin/postgres" -V))"
}

redis_up() {
  if ! redis-cli -p "$REDIS_PORT" ping >/dev/null 2>&1; then
    mkdir -p "$DATA/redis"
    redis-server --port "$REDIS_PORT" --bind 127.0.0.1 --dir "$DATA/redis" \
      --daemonize yes --logfile "$DATA/redis.log" --save "" >/dev/null
  fi
  echo "redis     127.0.0.1:$REDIS_PORT"
}

down() {
  local bin
  if [[ -f "$PGDATA/PG_VERSION" ]] && bin="$(find_pg_bin 2>/dev/null)"; then
    "$bin/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1 && "$bin/pg_ctl" -D "$PGDATA" -m fast stop >/dev/null
  fi
  redis-cli -p "$REDIS_PORT" shutdown nosave >/dev/null 2>&1 || true
  echo "stopped"
}

case "${1:-up}" in
  up) pg_up; redis_up ;;
  down) down ;;
  *) echo "usage: $0 [up|down]" >&2; exit 2 ;;
esac
