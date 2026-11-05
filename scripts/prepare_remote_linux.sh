#!/bin/sh
set -eu
[ "$(uname -s)" = Linux ] || { echo "Esta entrada requiere Linux" >&2; exit 2; }
exec sh "$(dirname -- "$0")/bootstrap_remote_host.sh" "$@"
