#!/bin/sh
# Fail fast with a clear message when the data volume is not writable by the container user.
set -e
DATA_DIR="${APP_DATA_DIR:-/data}"
if ! ( mkdir -p "$DATA_DIR" && touch "$DATA_DIR/.write-test" && rm -f "$DATA_DIR/.write-test" ) 2>/dev/null; then
  echo "ERROR: $DATA_DIR is not writable by uid $(id -u) gid $(id -g)." >&2
  echo "On the host run:  sudo chown -R $(id -u):$(id -g) ./data" >&2
  echo "or set PUID/PGID in .env to the owner of ./data (see README, 'Data directory permissions')." >&2
  exit 1
fi
exec "$@"
