#!/bin/bash
# Serialize resource-heavy build stages and retain their logs outside Git.
set -euo pipefail
cd "$(dirname "$0")/.."
name=${1:?Expected a log name and command}
shift
[[ $name =~ ^[a-z][a-z0-9-]*$ && $# -gt 0 ]] || exit 2
umask 077
mkdir -p .local/build/logs
exec 9>.local/build/workflow.lock
flock -n 9 || { echo 'Another build stage is running; wait for it to finish.' >&2; exit 1; }
log=".local/build/$name.log"
if [[ -f $log ]]; then
    mv "$log" ".local/build/logs/$name-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
fi
printf 'Running %s; follow progress with: tail -f %s\n' "$name" "$log"
if "$@" > "$log" 2>&1; then
    printf '%s completed. Log: %s\n' "$name" "$log"
else
    result=$?
    tail -n 40 "$log" >&2
    printf '%s failed (exit %s). Full log: %s\n' "$name" "$result" "$log" >&2
    exit "$result"
fi
