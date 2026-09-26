#!/bin/bash
# Offline image verification inside the pinned privileged builder container.
set -euo pipefail
[[ $# == 1 ]] || { echo 'Usage: verify-image.sh IMAGE' >&2; exit 2; }
image=$(realpath "$1")
cd "$(dirname "$0")/.."
python3 tools/image.py verify "$image"
builder=$(python3 -c 'import json; print(json.load(open("build/sources.lock.json"))["builder"]["image"])')
docker run --rm --privileged --entrypoint bash -v "$PWD:/project" \
    -v "$image:/image.img:ro" "$builder" -c '
    set -euo pipefail
    loop=$(losetup --find --show --read-only --partscan /image.img)
    mkdir -p /mnt/neo-root /mnt/neo-boot
    cleanup() {
        mountpoint -q /mnt/neo-boot && umount /mnt/neo-boot || true
        mountpoint -q /mnt/neo-root && umount /mnt/neo-root || true
        losetup -d "$loop"
    }
    trap cleanup EXIT
    for number in 1 2; do
        node="${loop##*/}p${number}"
        if [[ ! -b /dev/$node ]]; then
            IFS=: read -r major minor < "/sys/class/block/$node/dev"
            mknod -m 0600 "/dev/$node" b "$major" "$minor"
        fi
    done
    fsck.fat -n "${loop}p1"
    e2fsck -fn "${loop}p2"
    mount -o ro,noload "${loop}p2" /mnt/neo-root
    mount -o ro "${loop}p1" /mnt/neo-boot
    python3 /project/tools/verify-rootfs.py /mnt/neo-root /mnt/neo-boot
    dumpimage -l /mnt/neo-boot/uImage
    dumpimage -l /mnt/neo-boot/boot.scr
    '
