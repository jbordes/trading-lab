#!/bin/sh
set -eu
[ "$(uname -s)" = Darwin ] || { echo "Esta entrada requiere macOS" >&2; exit 2; }
exec sh "$(dirname -- "$0")/bootstrap_remote_host.sh" "$@"
