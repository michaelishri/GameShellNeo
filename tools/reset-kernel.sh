#!/bin/bash
# Preserve old scratch state; never delete provisioning, firmware or images.
set -euo pipefail
cd "$(dirname "$0")/.."
version=$(python3 -c 'import json; print(json.load(open("build/sources.lock.json"))["linux"]["tag"][1:])')
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
umask 077
archive=".local/previous-kernels/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$archive"
# Image assembly replaces the current provenance files. Retain them alongside
# the previous kernel, while keeping the large recovery images in artifacts/.
if [[ -d .local/artifacts ]]; then
    tar --exclude='*.img' --exclude='*.img.gz' -cf "$archive/artifact-metadata.tar" -C .local/artifacts .
fi
for path in ".local/sources/linux-$version" .local/build/kernel .local/kernel-install .local/build/kernel-completed.json; do
    if [[ -e $path ]]; then mv "$path" "$archive/"; fi
done
printf 'Previous kernel state retained in %s\nRun task build:kernel next.\n' "$archive"
