#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
    echo 'Image builds currently require the Intel/amd64 Linux Docker host.' >&2; exit 1;
}
for program in bash python3 docker git curl tar cc flock ssh-keygen; do
    command -v "$program" >/dev/null || { echo "Missing prerequisite: $program" >&2; exit 1; }
done
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
docker info >/dev/null
umask 077
mkdir -p .local/build
chmod 700 .local
echo 'Build prerequisites and Docker access: ready.'
if python3 -c 'import paramiko' 2>/dev/null; then
    echo 'Paramiko for device/Mac tasks: available.'
else
    echo 'Device/Mac tasks also need Paramiko; see README. Local builds can proceed.'
fi
