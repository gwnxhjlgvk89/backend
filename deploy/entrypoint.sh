#!/bin/sh
set -eu
if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
    # This is a per-container metrics directory, never a shared data volume.
    case "$PROMETHEUS_MULTIPROC_DIR" in
      /metrics) rm -f /metrics/*.db ;;
      *) echo 'Unexpected metrics directory' >&2; exit 1 ;;
    esac
fi
exec "$@"
